"""对话服务层：把同步的 LangGraph 工作流包装成带事件流的聊天服务。

设计要点：
- 不改动 src/ 下任何业务代码，只做编排、持久化与流式桥接；
- 会话历史每次从数据库读取，后端自身无内存会话状态（重启不丢、可水平扩展）；
- 流式输出优先用 LangGraph 的多模式流 ["messages", "updates"] 获取真实 token，
  旧版本 langgraph 不支持多模式时自动回退 updates 模式 + 全文切片伪流；
- 与原 Gradio 版的差异：AgentGraph.run() 内嵌的超时线程 hack 已移除，
  超时控制交由部署层网关处理。
"""

import base64
import os
import time
import uuid
from typing import Any, Dict, Generator, List, Optional, Tuple

from src.agent.state import init_state
from src.utils.logger import setup_logger

# 延迟导入：保持模块导入轻量，依赖懒加载单例
Event = Tuple[str, Dict[str, Any]]

HISTORY_WINDOW = 20   # 进入 LLM 上下文的历史消息条数上限
PSEUDO_CHUNK = 24     # 回退伪流式时的切片长度（字符）
# 节点内部捕获异常后写入 final_answer 的道歉语前缀（见 src/agent/nodes.py），
# 用于识别"工作流正常结束但实际内部出错"的情况
APOLOGY_PREFIX = "抱歉，处理您的请求时出错"

logger = setup_logger("chat_service")


def _get_crud():
    from src.database.crud import (
        create_session,
        get_session_by_id,
        update_session,
    )

    return create_session, get_session_by_id, update_session


def _get_agent_graph():
    from backend.core.deps import get_agent_graph

    return get_agent_graph()


def _uuid_or_none(value: Optional[str]) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def _derive_title(first_user_message: str) -> str:
    text = first_user_message.strip()
    if not text:
        return "新对话"
    return f"{text[:30]}..." if len(text) > 30 else text


def ensure_session(session_id: Optional[str]) -> str:
    """校验或创建会话，返回确保存在于数据库的 session_id 字符串。

    LangGraph 内部会把 MCP 调用日志按该 UUID 外键落库，因此不能信任
    客户端传来的任意 ID——必须保证对应的 chat_session 行真实存在。
    """
    create_session, get_session_by_id, _ = _get_crud()

    uid = _uuid_or_none(session_id)
    if uid is not None:
        try:
            if get_session_by_id(uid):
                return str(uid)
            create_session(title="新对话", messages=[], session_id=uid)
            return str(uid)
        except Exception as exc:
            logger.warning(f"Session lookup failed, creating a new one: {exc}")
    new_uid = uuid.uuid4()
    create_session(title="新对话", messages=[], session_id=new_uid)
    return str(new_uid)


def _load_history(session_id: str) -> List[Dict[str, Any]]:
    """从数据库加载最近 HISTORY_WINDOW 条历史消息（user/assistant 文本）。"""
    _, get_session_by_id, _ = _get_crud()
    uid = _uuid_or_none(session_id)
    if uid is None:
        return []
    try:
        session = get_session_by_id(uid)
    except Exception as exc:
        logger.warning(f"Failed to load history for {session_id}: {exc}")
        return []

    messages = (session or {}).get("messages") or []
    cleaned = [
        {"role": msg["role"], "content": msg.get("content", "")}
        for msg in messages
        if isinstance(msg, dict)
        and msg.get("role") in ("user", "assistant")
        and isinstance(msg.get("content"), str)
    ]
    return cleaned[-HISTORY_WINDOW:]


def _persist_exchange(session_id: str, message: str, answer: str, set_title: bool) -> None:
    """把一轮问答追加到数据库会话记录（失败只告警，不影响响应）。"""
    _, _, update_session = _get_crud()
    uid = _uuid_or_none(session_id)
    if uid is None:
        return
    kwargs: Dict[str, Any] = {
        "append_messages": [
            {"role": "user", "content": message},
            {"role": "assistant", "content": answer},
        ]
    }
    if set_title:
        kwargs["title"] = _derive_title(message)
    try:
        update_session(uid, **kwargs)
    except Exception as exc:
        logger.warning(f"Failed to persist exchange: {exc}")


def _save_memory(agent_graph, message: str, answer: str, session_id: str) -> None:
    """复用 AgentGraph.run() 收尾时的长期记忆保存逻辑。

    该方法目前是私有接口（_post_session_cleanup），后续重构应将其
    提升为公共方法或独立服务，避免跨层调用私有成员。
    """
    try:
        from src.agent.memory import get_memory

        agent_graph._post_session_cleanup(
            memory=get_memory(),
            user_input=message,
            result={"final_answer": answer},
            session_id=session_id,
        )
    except Exception as exc:
        logger.warning(f"Post-session memory save failed: {exc}")


def _synthesize_audio(answer: str) -> Optional[str]:
    try:
        from backend.core.deps import get_text_to_speech

        audio_bytes = get_text_to_speech().synthesize(answer, output_format="mp3")
        if audio_bytes and len(audio_bytes) > 0:
            return "data:audio/mp3;base64," + base64.b64encode(audio_bytes).decode()
    except Exception as exc:
        logger.warning(f"TTS synthesis failed: {exc}")
    return None


def _extract_delta(message_chunk: Any) -> str:
    """兼容不同返回结构的增量文本提取。"""
    content = getattr(message_chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # 部分 OpenAI 兼容模型按 [{"type":"text","text":"..."}, ...] 分片返回
        parts = [part.get("text", "") if isinstance(part, dict) else str(part) for part in content]
        return "".join(parts)
    return ""


def iter_chat_events(
    message: str,
    session_id: str,
    model_type: str = "deepseek",
    images: Optional[List[str]] = None,
    want_tts: bool = False,
    _allow_fallback: bool = True,
    _force_updates: bool = False,
) -> Generator[Event, None, None]:
    """运行一次完整问答并逐步产出 (event, data) 事件流。

    事件类型：
    - start  {"session_id"}                        请求受理完成（会话已就绪）
    - status {"node"}                              工作流节点切换（llm_inference 等）
    - token  {"delta"}                             增量回答文本（真实 token 或切片）
    - tts    {"audio"}                             mp3 的 base64 data URI（可选）
    - done   {"session_id", "answer", "elapsed_ms"}
    - error  {"message"}

    流模式由环境变量 CHAT_STREAM_MODE 控制：
    - updates（默认）：仅推送节点级状态事件，回答最后切片推送。
      与 Gradio 版行为一致，对任何 langchain 版本组合都安全；
    - multi：额外尝试 messages 模式获取真实 token。已知在
      langgraph 1.2.9 + langchain-core 1.4.9 组合下，非流式 invoke
      会触发 'AIMessage' object has no attribute 'generation_info'
      崩溃并被节点吞掉，因此该模式下若检测到失败会自动降级重跑一次。
    """
    started = time.time()
    yield "start", {"session_id": session_id}

    use_multi = (
        not _force_updates
        and os.getenv("CHAT_STREAM_MODE", "updates").strip().lower() == "multi"
    )

    history_before = _load_history(session_id)
    state = init_state(
        message,
        uuid.UUID(session_id),
        model_type,
        list(images or []),
        history_before,
    )
    compiled = _get_agent_graph().compile()

    streamed_chars = 0
    final_answer = ""
    stream_error: Optional[BaseException] = None

    try:
        try:
            if use_multi:
                events = compiled.stream(state, stream_mode=["messages", "updates"])
            else:
                events = (("updates", p) for p in compiled.stream(state, stream_mode="updates"))
        except TypeError:
            # 旧版 langgraph 不接受多模式列表，退化为仅 updates 事件流
            events = (("updates", p) for p in compiled.stream(state, stream_mode="updates"))
            logger.info("Multi-mode streaming unavailable, falling back to updates-only")

        try:
            for mode, payload in events:
                if mode == "updates":
                    if not isinstance(payload, dict):
                        continue
                    for node, node_update in payload.items():
                        if node == "__end__":
                            continue
                        yield "status", {"node": str(node)}
                        if isinstance(node_update, dict) and node_update.get("final_answer"):
                            final_answer = node_update["final_answer"]
                else:
                    # messages 模式的 payload 是 (message_chunk, metadata)
                    metadata = payload[1] if isinstance(payload, tuple) else {}
                    node = metadata.get("langgraph_node") if isinstance(metadata, dict) else None
                    if node != "answer_generation":
                        # llm_inference 输出的是意图解析 JSON，不应进入聊天窗口
                        continue
                    delta = _extract_delta(payload[0])
                    if delta:
                        streamed_chars += len(delta)
                        yield "token", {"delta": delta}
        except Exception as exc:
            # 消费流过程中的异常先记下，统一在下方决定降级或抛出
            stream_error = exc

        # messages 模式的失败有两种表现：异常直接抛出，或被节点 try/except
        # 吞掉后以道歉语 final_answer 收场。两种都通过"没产生过真实 token"
        # 且开启降级来识别，用强制 updates 模式重跑一次（代价是失败时多一次调用）。
        poisoned = streamed_chars == 0 and final_answer.startswith(APOLOGY_PREFIX)
        if use_multi and _allow_fallback and (stream_error is not None or poisoned):
            logger.warning(
                f"messages 流模式失败（{stream_error or final_answer[:60]}），"
                "自动降级为 updates 模式重跑"
            )
            yield from iter_chat_events(
                message,
                session_id,
                model_type,
                images,
                want_tts,
                _allow_fallback=False,
                _force_updates=True,
            )
            return
        if stream_error is not None:
            raise stream_error

        answer = (final_answer or "").strip()
        if not streamed_chars and answer:
            # 真实 token 流不可用时切片推送完整回答，前端只需面对一种 token 事件
            for i in range(0, len(answer), PSEUDO_CHUNK):
                yield "token", {"delta": answer[i : i + PSEUDO_CHUNK]}
        if not answer and not streamed_chars:
            answer = "抱歉，未能生成有效回答，请重试。"

        elapsed_ms = int((time.time() - started) * 1000)

        # 先发出 done：客户端收到完整回答后即可结束动画（切 markdown、停光标）。
        # 数据库持久化与长期记忆收尾放到 done 之后执行——Supabase 偶发
        # 超时（10-30s）时不再拖住前端等待，与新会话的持久化互不阻塞。
        yield "done", {"session_id": session_id, "answer": answer, "elapsed_ms": elapsed_ms}

        _persist_exchange(session_id, message, answer, set_title=not history_before)
        _save_memory(_get_agent_graph(), message, answer, session_id)

        if want_tts and len(answer) >= 2:
            audio = _synthesize_audio(answer)
            if audio:
                yield "tts", {"audio": audio}
    except Exception as exc:
        logger.error(f"Chat stream failed: {exc}", exc_info=True)
        yield "error", {"message": f"处理请求时出错：{exc}"}


def run_chat_sync(
    message: str,
    session_id: str,
    model_type: str = "deepseek",
    images: Optional[List[str]] = None,
    want_tts: bool = False,
) -> Dict[str, Any]:
    """非流式入口：消费同一份事件流取最终结果，两条链路行为天然一致。"""
    collected: List[str] = []
    audio: Optional[str] = None
    result: Dict[str, Any] = {}

    for event, data in iter_chat_events(message, session_id, model_type, images, want_tts):
        if event == "token":
            collected.append(data["delta"])
        elif event == "tts":
            audio = data["audio"]
        elif event == "done":
            result = data
        elif event == "error":
            raise RuntimeError(data["message"])

    if not result:
        result = {"session_id": session_id, "answer": "".join(collected), "elapsed_ms": -1}
    if audio:
        result["audio"] = audio
    return result
