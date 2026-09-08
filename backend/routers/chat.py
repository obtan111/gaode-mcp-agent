"""聊天路由：提供普通 JSON、SSE 流式与 WebSocket 流式三种消费方式。"""

import asyncio
import json
import logging
import re
from typing import Any, Dict, Generator, Optional, Tuple

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from backend.schemas.chat import ChatRequest, ChatResponse
from backend.services.agent_runner import ensure_session, iter_chat_events, run_chat_sync
from src.utils.stream_bus import set_token_sink

logger = logging.getLogger("backend.chat_ws")

router = APIRouter(prefix="/api/chat", tags=["chat"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    # Nginx 反向代理默认会缓冲响应，必须显式关闭才能看到逐字效果
    "X-Accel-Buffering": "no",
}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """一次性返回完整回答。

    同步路由由 FastAPI 自动放入线程池执行，不会阻塞事件循环，
    适合作为前端的保底通道（SSE 不可用时降级）。
    """
    session_id = ensure_session(req.session_id)
    result = run_chat_sync(req.message, session_id, req.model_type, req.images, req.tts)
    return ChatResponse(**result)


@router.post("/stream")
def chat_stream(req: ChatRequest) -> StreamingResponse:
    """SSE 流式回答，事件定义见 services.agent_runner.iter_chat_events。"""
    session_id = ensure_session(req.session_id)

    def source() -> Generator[str, None, None]:
        for event, data in iter_chat_events(req.message, session_id, req.model_type, req.images, req.tts):
            yield _sse(event, data)

    return StreamingResponse(source(), media_type="text/event-stream", headers=_SSE_HEADERS)


# ---------------------------------------------------------------------------
# WebSocket 流式聊天（微信小程序 / 移动端使用）
# ---------------------------------------------------------------------------

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _looks_like_itinerary(obj: Any) -> bool:
    """判定解析出的 JSON 是否具备行程计划结构（对齐 src/agent/prompts.py 的 schema）。"""
    if not isinstance(obj, dict):
        return False
    if isinstance(obj.get("daily_itinerary"), list) and obj.get("daily_itinerary"):
        return True
    if isinstance(obj.get("days"), list) and obj.get("days"):
        return True
    if obj.get("destination") and isinstance(obj.get("days"), (int, float)):
        return True
    return False


def _extract_itinerary(answer: str, user_message: str = "") -> Optional[Dict[str, Any]]:
    """从最终回答文本中尽力提取行程 JSON，提取不到返回 None（不影响正常回答）。

    两条通道：
    1) answer 中本身携带 JSON（```json 围栏或裸对象），直接解析校验；
    2) 否则把 agent 输出的结构化 markdown（## Day N + ### 上午/下午/晚上 分节）
       解析为与 TRAVEL_PLAN_PROMPT 对齐的行程对象。
    user_message 用于更可靠地推断目的地（用户提问里的「长沙2日游」）。
    """
    if not answer:
        return None
    candidates: list = [m.group(1) for m in _JSON_FENCE_RE.finditer(answer)]
    start, end = answer.find("{"), answer.rfind("}")
    if start != -1 and end > start:
        candidates.append(answer[start : end + 1])
    for text in candidates:
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            continue
        if _looks_like_itinerary(obj):
            return obj
    return _extract_itinerary_from_text(answer, user_message)


_DAY_HEAD_RE = re.compile(
    r"^\s*#{1,4}\s*[^\u4e00-\u9fa5A-Za-z0-9]*?(?:Day\s*(\d+)|第\s*(\d+)\s*天)\b",
    re.IGNORECASE,
)
# 时段头两种形态：### 上午：xxx  与  **上午 | xxx**
_SLOT_HEAD_RE = re.compile(
    r"^\s*#{1,4}\s*((?:上午|中午|下午|傍晚|晚上|夜间|夜|午餐|晚餐)"
    r"(?:[、/]?(?:上午|中午|下午|傍晚|晚上|夜间|夜|午餐|晚餐))*)\s*[：:]\s*(.+?)\s*$"
)
_BOLD_SLOT_HEAD_RE = re.compile(
    r"^\s*\*\*((?:上午|中午|下午|傍晚|晚上|夜间|夜|午餐|晚餐)"
    r"(?:[、/]?(?:上午|中午|下午|傍晚|晚上|夜间|夜|午餐|晚餐))*)\s*[|｜：:]\s*(.+?)\s*\*\*(?:[（(][^）)]*[）)])?\s*$"
)
# 住宿/交通/贴士等非行程小节：出现后停止往当前时段累积描述
_NON_SLOT_SECTION_RE = re.compile(
    r"^\s*#{1,4}\s*(?:💡|🏨|🚇|⚠️)?\s*(?:住宿|交通|小贴士|注意事项|注意|建议|美食|费用|预算|总结)"
)
_SLOT_MAP = {
    "上午": "morning",
    "中午": "morning",
    "午餐": "morning",
    "下午": "afternoon",
    "傍晚": "evening",
    "晚上": "evening",
    "晚餐": "evening",
    "夜间": "evening",
    "夜": "evening",
}


def _match_slot(line: str) -> Optional[Tuple[str, str]]:
    """识别时段行，返回 (slot_key, activity)，非时段行返回 None。"""
    m = _SLOT_HEAD_RE.match(line)
    if m:
        key = _SLOT_MAP[m.group(1).split("/")[0].split("、")[0]]
        return key, m.group(2).strip()
    m = _BOLD_SLOT_HEAD_RE.match(line)
    if m:
        key = _SLOT_MAP[m.group(1).split("/")[0].split("、")[0]]
        activity = m.group(2).strip()
        if activity.startswith("推荐："):
            activity = activity[3:]
        return key, activity
    return None


def _clean_description(text: str) -> str:
    """去掉 description 里的 markdown 强调/代码标记，保留换行与列表。"""
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text.strip()


def _extract_itinerary_from_text(answer: str, user_message: str = "") -> Optional[Dict[str, Any]]:
    """把 agent 的 markdown 行程文本解析为行程 JSON（尽力而为，失败返回 None）。

    兼容的段落形态（实测后端输出）：
        ## 📍 Day 1（9/9 周三）：山水洲城经典线
        ### 上午：岳麓山风景名胜区
        ### 下午：橘子洲风景名胜区
        ### 傍晚/晚上：湘江东岸休闲夜色
    """
    lines = answer.splitlines()
    days: list = []
    cur_day: Optional[dict] = None
    cur_slot: Optional[str] = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        dm = _DAY_HEAD_RE.match(line)
        if dm:
            day_num = int(dm.group(1) or dm.group(2))
            title = line.split("：", 1)[1].strip() if "：" in line else ""
            date = ""
            dm_date = re.search(r"[（(]([^（()）]{1,20})[）)]", line)
            if dm_date and re.search(r"[\/月日\-]", dm_date.group(1)):
                date = dm_date.group(1)
            # 单行路线型 Day 头（如「岳麓山 → 橘子洲 → 太平街」）存为 route 兜底
            route = title if ("→" in title or "->" in title or "｜" in title or len(title) > 12) else ""
            cur_day = {
                "day": day_num,
                "date": date,
                "weather": "",
                "morning": None,
                "afternoon": None,
                "evening": None,
                "title": title,
                "route": route,
            }
            days.append(cur_day)
            cur_slot = None
            continue
        slot = _match_slot(line)
        if slot is not None:
            if cur_day is None:
                cur_day = {
                    "day": len(days) + 1,
                    "date": "",
                    "weather": "",
                    "morning": None,
                    "afternoon": None,
                    "evening": None,
                    "title": "",
                }
                days.append(cur_day)
            slot_key, activity = slot
            location = _extract_location(activity)
            if cur_day.get(slot_key) is None:
                cur_day[slot_key] = {
                    "activity": activity,
                    "location": location,
                    "transport": "",
                    "duration": "",
                    "cost": "",
                    "description": "",
                }
            elif activity and activity not in cur_day[slot_key]["activity"]:
                # 同一时段多次出现（如「上午|天心阁」后又「上午/中午|杜甫江阁」）：
                # 合并活动名，避免覆盖丢失
                cur_day[slot_key]["activity"] += "、" + activity
            cur_slot = slot_key
            continue
        if _NON_SLOT_SECTION_RE.match(line):
            cur_slot = None
            continue
        if cur_slot is not None and cur_day is not None and cur_day.get(cur_slot) is not None:
            cur_day[cur_slot]["description"] += line + "\n"

    if not days:
        return None

    destination = _guess_destination(user_message) or _guess_destination(answer)
    daily_itinerary = []
    for d in days:
        entry: Dict[str, Any] = {"day": d["day"], "date": d["date"], "weather": d["weather"]}
        if d.get("route"):
            entry["route"] = d["route"]
        for key in ("morning", "afternoon", "evening"):
            slot = d.get(key)
            if not slot:
                continue
            clean = {k: v for k, v in slot.items() if k != "description" and v}
            if slot.get("description"):
                clean["description"] = _clean_description(slot["description"])
            entry[key] = clean
        daily_itinerary.append(entry)

    return {
        "title": f"{destination}{len(days)}日游" if destination else "旅行计划",
        "destination": destination,
        "days": len(days),
        "budget": "",
        "weather_summary": "",
        "daily_itinerary": daily_itinerary,
        "tips": [],
    }


def _extract_location(activity: str) -> str:
    """从活动标题里尽力提取地点（【】、（）括号优先）。"""
    for opener, closer in (("【", "】"), ("（", "）"), ("(", ")")):
        if opener in activity and closer in activity:
            return activity.split(opener, 1)[1].split(closer, 1)[0].strip()
    return ""


# 「X日游」前常见的前缀助词/动词/量词，地名提取时从头跳过
_NON_DEST_CHARS = "的了份为是在至去到来给和与把将帮我你要这那准备安排行程计划攻略如下一份查收请点规划游个"


def _guess_destination(text: str) -> str:
    """从「长沙2日游 / 北京三日游 / 桂林两日游」这类短语里提取地名。

    取「日/天游」前的连续汉字串，跳过头部助词/动词后，
    第一个非虚词位置起的地名块即为目的地（中文地名几乎都在 2~6 字）。
    """
    m = re.search(
        r"([\u4e00-\u9fa5]+)\s*(?:\d+|[一二三四五六七八九十两])\s*[日天]\s*游",
        text,
    )
    if not m:
        return ""
    s = m.group(1)
    for idx, ch in enumerate(s):
        if ch in _NON_DEST_CHARS:
            continue
        cand = s[idx:]
        return cand if len(cand) <= 6 else cand[:6]
    return ""


async def _pump_events(
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue,
    message: str,
    session_id: str,
    model_type: str,
    images: list,
    tts: bool,
) -> None:
    """把同步生成器 iter_chat_events 的事件逐一桥接进 asyncio.Queue。

    iter_chat_events 是同步生成器且内部调用阻塞的 LLM/RAG 服务，因此放进
    线程池（to_thread）执行；线程内通过 run_coroutine_threadsafe 把事件投递
    给事件循环上的队列，WebSocket 主协程负责取事件并下发。
    事件末尾补发哨兵 ("__close__", {}) 通知主协程本轮结束。
    """
    def consume() -> None:
        # 真流式 token 旁路：answer_generation 节点内流式生成的增量文本，
        # 经 stream_bus 实时桥接进事件队列（线程安全），无需等节点完成。
        # 单连接同刻单轮，模块级 sink 安全；本轮结束（finally）必摘除。
        set_token_sink(lambda text: asyncio.run_coroutine_threadsafe(
            queue.put(("token", {"delta": text})), loop).result())
        try:
            for event, data in iter_chat_events(message, session_id, model_type, images, tts):
                asyncio.run_coroutine_threadsafe(queue.put((event, data)), loop).result()
                if event == "done":
                    itinerary = _extract_itinerary(data.get("answer") or "", message)
                    if itinerary:
                        asyncio.run_coroutine_threadsafe(queue.put(("itinerary", itinerary)), loop).result()
        except Exception as exc:  # 生成器抛出预期外异常时兜底
            logger.error(f"WS event pump failed: {exc}", exc_info=True)
            try:
                asyncio.run_coroutine_threadsafe(
                    queue.put(("error", {"message": f"处理请求时出错：{exc}"})), loop
                ).result()
            except Exception:
                pass
        finally:
            set_token_sink(None)
            try:
                asyncio.run_coroutine_threadsafe(queue.put(("__close__", {})), loop).result()
            except Exception:
                pass

    await asyncio.to_thread(consume)


async def _handle_client_message(
    websocket: WebSocket,
    raw: str,
    start_chat,
) -> None:
    """解析客户端消息并按 action 分发；坏消息回 error 事件而不断开连接。"""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        await websocket.send_json({"event": "error", "data": {"message": "无效的 JSON 消息"}})
        return
    if not isinstance(payload, dict):
        await websocket.send_json({"event": "error", "data": {"message": "消息必须是 JSON 对象"}})
        return
    action = payload.get("action") or payload.get("type") or "chat"
    if action == "ping":
        await websocket.send_json({"event": "pong", "data": {}})
    elif action == "chat":
        await start_chat(payload)
    else:
        await websocket.send_json({"event": "error", "data": {"message": f"未知 action: {action}"}})


@router.websocket("/ws")
async def chat_ws(websocket: WebSocket) -> None:
    """WebSocket 流式聊天端点（/api/chat/ws）。

    客户端 -> 服务端：
      {"action":"chat","message":"...","session_id":"...","model_type":"deepseek","tts":false}
      {"action":"ping"}                                      心跳
    （一条连接同一时刻只处理一个问答；上一条未结束时再发 chat 会收到 error 事件）

    服务端 -> 客户端（{"event": ..., "data": ...}）：
      start       {"session_id"}                             会话已就绪（新会话时返回新 ID）
      status      {"node"}                                   工作流节点切换（前端可忽略）
      token       {"delta"}                                  增量文本
      itinerary   {行程 JSON}                                 answer 中检测到行程计划时额外发出
      done        {"session_id","answer","elapsed_ms"}       本轮结束（answer 为完整文本）
      tts         {"audio"}                                  TTS base64 data URI（仅请求 tts=true）
      error       {"message"}
    """
    await websocket.accept()
    loop = asyncio.get_running_loop()
    session_id: Optional[str] = None
    queue: Optional[asyncio.Queue] = None
    pump: Optional[asyncio.Task] = None

    async def start_chat(payload: Dict[str, Any]) -> None:
        nonlocal session_id, queue, pump
        message = (payload.get("message") or "").strip()
        if not message:
            await websocket.send_json({"event": "error", "data": {"message": "消息不能为空"}})
            return
        if pump is not None:
            await websocket.send_json(
                {"event": "error", "data": {"message": "上一条消息仍在处理中，请稍候"}}
            )
            return
        # 沿用 POST/SSE 链路：先确保会话存在，再跑事件流
        session_id = ensure_session(payload.get("session_id") or session_id)
        queue = asyncio.Queue()
        pump = asyncio.create_task(
            _pump_events(
                loop,
                queue,
                message,
                session_id,
                payload.get("model_type") or "deepseek",
                payload.get("images") or [],
                bool(payload.get("tts", False)),
            )
        )

    try:
        while True:
            if pump is not None:
                # 本轮运行中：同时监听事件队列与客户端新消息，先到先处理
                get_task = asyncio.create_task(queue.get())
                recv_task = asyncio.create_task(websocket.receive_text())
                done, pending = await asyncio.wait(
                    {get_task, recv_task}, return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()
                if get_task in done:
                    event, data = get_task.result()
                    if event == "__close__":
                        await pump  # 事件已全部取出，等泵任务收尾
                        pump = None
                        queue = None
                    else:
                        await websocket.send_json({"event": event, "data": data})
                if recv_task in done:
                    await _handle_client_message(websocket, recv_task.result(), start_chat)
            else:
                raw = await websocket.receive_text()
                await _handle_client_message(websocket, raw, start_chat)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as exc:
        logger.error(f"WebSocket error: {exc}", exc_info=True)
        try:
            await websocket.send_json({"event": "error", "data": {"message": f"连接错误：{exc}"}})
        except Exception:
            pass
    finally:
        if pump is not None:
            pump.cancel()
