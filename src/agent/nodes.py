import json
from typing import Dict, Any, List

from src.config import Config
from src.llm.model_factory import ModelFactory
from src.mcp.mcp_client import MCPClient
from src.database.crud import log_mcp_call
from src.utils.logger import setup_logger
from src.agent.state import AgentState, update_state, add_mcp_result, increment_call_count, add_rag_result
from src.agent.prompts import SYSTEM_PROMPT, TOOL_CALL_PROMPT, ANSWER_GENERATION_PROMPT
from src.agent.memory import get_memory
from src.rag.retrieval_pipeline import RetrievalPipeline

logger = setup_logger("agent_nodes")

_model_cache = {}


def _parse_llm_json(content: str) -> Dict[str, Any]:
    """
    健壮地解析 LLM 返回的 JSON。
    
    处理以下常见格式问题：
    1. Markdown 代码块标记（```json ... ```）
    2. 首尾空白字符
    3. 多余的转义字符
    4. LLM 思考过程 + JSON 混合输出（从文本中提取 JSON）
    
    参数：
    - content: LLM 返回的原始内容
    
    返回：
    - 解析后的 JSON 对象
    
    抛出：
    - json.JSONDecodeError: 无法解析为有效 JSON
    """
    cleaned = content.strip()
    
    # 尝试直接解析
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    
    # 去除 Markdown 代码块标记
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        if len(lines) > 2:
            cleaned = "\n".join(lines[1:-1])
        else:
            cleaned = ""
    
    cleaned = cleaned.strip()
    
    # 尝试解析去除 Markdown 后的内容
    if cleaned:
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
    
    # 从混合文本中提取 JSON 对象
    # 查找 { 开始，} 结束的内容
    json_start = cleaned.find("{")
    json_end = cleaned.rfind("}")
    
    if json_start != -1 and json_end != -1 and json_start < json_end:
        json_str = cleaned[json_start:json_end + 1]
        try:
            result = json.loads(json_str)
            logger.info(f"Successfully extracted JSON from mixed text: {json_str[:100]}...")
            return result
        except json.JSONDecodeError:
            pass
    
    # 尝试查找完整的 JSON 对象（处理嵌套的花括号）
    depth = 0
    start_idx = -1
    for i, char in enumerate(cleaned):
        if char == '{':
            if depth == 0:
                start_idx = i
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0 and start_idx != -1:
                json_str = cleaned[start_idx:i + 1]
                try:
                    result = json.loads(json_str)
                    logger.info(f"Successfully extracted nested JSON: {json_str[:100]}...")
                    return result
                except json.JSONDecodeError:
                    start_idx = -1
                    continue
    
    raise json.JSONDecodeError("Cannot find valid JSON in content", content, 0)


def _should_retrieve(user_input: str, model) -> bool:
    """
    基于关键词快速判断是否需要检索知识库（避免额外LLM调用延迟）。
    
    规则：
    - 需要检索：命中专业/内部/法规相关关键词
    - 不需要检索：命中常识/闲聊/工具调用关键词
    - 不确定时（未命中任何规则）：为安全起见执行检索
    
    参数：
    - user_input: 用户输入的问题
    - model: LLM模型实例（保留用于未来扩展）
    
    返回：
    - True: 需要检索知识库
    - False: 不需要检索，直接回答
    """
    if not user_input or not user_input.strip():
        return False
    
    text = user_input.lower()
    
    # 工具调用请求 - 不需要检索
    tool_keywords = ["天气", "地图", "路线", "导航", "查天气", "时间", "几点", "日期", "旅游", "行程"]
    for kw in tool_keywords:
        if kw in text:
            logger.info(f"RAG检索判断: 检测到工具调用关键词 '{kw}'，跳过检索")
            return False
    
    # 明确不需要检索的场景（常识/闲聊）
    no_rag_keywords = [
        "你好", "hello", "hi", "谢谢", "再见",
        "python是什么", "java是什么", "你是谁", "你叫什么",
        "天气怎么样", "今天天气",
    ]
    for kw in no_rag_keywords:
        if kw in text:
            logger.info(f"RAG检索判断: 检测到常识关键词 '{kw}'，跳过检索")
            return False
    
    # 需要检索的场景（专业/内部/法规）
    rag_keywords = [
        "公司", "规定", "制度", "政策", "员工手册", "考勤", "年假", "社保",
        "法律", "法规", "条款", "条例", "合同", "劳动法", "合同法",
        "产品", "服务", "文档", "手册", "指南", "规范", "流程",
        "医保", "报销", "理赔", "保险",
        "根据", "按照", "依照", "依据",
        "几个点", "几条", "多少条", "第几条",
    ]
    for kw in rag_keywords:
        if kw in text:
            logger.info(f"RAG检索判断: 检测到检索关键词 '{kw}'，执行检索")
            return True
    
    # 短问题且非专业 - 不检索
    if len(user_input.strip()) <= 4:
        logger.info(f"RAG检索判断: 问题过短，跳过检索")
        return False
    
    # 默认检索（安全起见）
    logger.info(f"RAG检索判断: 未命中规则，默认执行检索")
    return True


def llm_inference_node(state: AgentState) -> AgentState:
    """
    LLM 推理节点：负责意图识别和工具选择。
    
    该节点的核心职责：
    1. 获取当前可用的工具列表
    2. 从长期记忆中检索相关上下文
    3. 构建包含工具描述和记忆上下文的提示词
    4. 调用 LLM 进行推理
    5. 解析 LLM 返回的 JSON 结果
    6. 根据结果决定下一步：调用工具或直接回答
    
    LLM 返回的 JSON 格式：
    {
        "need_tool": true/false,
        "tool_calls": [
            {"tool_name": "工具名", "method_name": "方法名", "parameters": {...}}
        ],
        "reason": "说明"
    }
    
    参数：
    - state: 当前代理状态
    
    返回：
    - 更新后的状态，包含工具调用列表或最终回答
    """
    config = Config()
    
    model_type = state.get("model_type", "deepseek")
    image_urls = state.get("image_urls", [])
    
    if image_urls and model_type not in ("zhipu-4v",):
        logger.info(f"Image uploaded with {model_type}, auto-switching to zhipu-4v for vision support")
        model_type = "zhipu-4v"
        state = update_state(state, model_type=model_type)
    
    if model_type not in _model_cache:
        model_factory = ModelFactory()
        _model_cache[model_type] = model_factory.create_model(model_type)
        logger.info(f"Cached model for {model_type}")
    
    model = _model_cache[model_type]
    
    memory = get_memory()
    memory_context = ""
    try:
        memory_context = memory.get_relevant_context(state["user_input"], max_memories=5)
        if memory_context:
            logger.info(f"Memory context retrieved: {len(memory_context)} chars")
    except Exception as e:
        logger.warning(f"Failed to get memory context: {e}")
    
    rag_results = []
    need_retrieval = _should_retrieve(state["user_input"], model)
    
    if need_retrieval:
        logger.info(f"LLM判断需要检索知识库，执行RAG检索")
        try:
            pipeline = RetrievalPipeline()
            rag_results = pipeline.retrieve(state["user_input"], kb_name=None)
            logger.info(f"RAG检索完成，找到 {len(rag_results)} 条结果")
        except Exception as e:
            logger.error(f"RAG检索失败: {str(e)}")
    else:
        logger.info(f"LLM判断不需要检索知识库，跳过RAG检索")
    
    if rag_results:
        state = add_rag_result(state, rag_results)
    
    tool_list = MCPClient.get_all_available_functions()
    tool_list_str = json.dumps(tool_list, ensure_ascii=False, indent=2)
    
    prompt = TOOL_CALL_PROMPT.format(tool_list=tool_list_str)
    
    user_message = {
        "role": "user",
        "content": state["user_input"],
    }
    
    image_urls = state.get("image_urls", [])
    if image_urls:
        user_message["additional_kwargs"] = {"image_urls": image_urls}
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]
    
    if memory_context:
        messages.append({"role": "system", "content": f"【长期记忆上下文】\n{memory_context}"})
    
    chat_history = state.get("chat_history", [])
    for msg in chat_history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": content})
    
    messages.append({"role": "system", "content": prompt})
    messages.append(user_message)
    
    logger.info(f"LLM inference node called, user_input: {state['user_input'][:50]}...")
    
    try:
        response = model.invoke(messages)
        content = response.content or ""
        
        logger.info(f"LLM response received: {content[:100]}...")
        
        try:
            result = _parse_llm_json(content)
        except json.JSONDecodeError:
            logger.warning("LLM response is not valid JSON, treating as direct answer")
            return update_state(
                state,
                final_answer=content,
                current_step="finish",
            )
        
        if result.get("need_tool"):
            return update_state(
                state,
                tool_calls=result.get("tool_calls", []),
                tool_list=tool_list,
                current_step="tool_execution",
            )
        else:
            answer = result.get("answer", "")
            try:
                memory = get_memory()
                session_id = str(state.get("session_id", "unknown"))
                if answer and len(answer) > 10:
                    memory.add_session_summary(
                        session_id=session_id,
                        summary=answer[:500],
                        key_topics=[state["user_input"][:50]],
                    )
            except Exception as e:
                logger.warning(f"Failed to save session summary: {e}")
            
            return update_state(
                state,
                final_answer=answer,
                current_step="finish",
            )
    
    except Exception as e:
        logger.error(f"LLM inference failed: {str(e)}", exc_info=True)
        return update_state(
            state,
            final_answer=f"抱歉，处理您的请求时出错：{str(e)}",
            current_step="finish",
        )


def mcp_execution_node(state: AgentState) -> AgentState:
    """
    MCP 工具执行节点：执行 LLM 决定的工具调用。
    
    该节点的核心职责：
    1. 遍历 state["tool_calls"] 中的所有工具调用
    2. 通过 MCPClient 调度执行每个工具方法
    3. 将工具执行结果添加到 state["mcp_results"]
    4. 更新工具调用计数器
    5. 判断是否达到最大调用次数限制
    
    参数：
    - state: 当前代理状态，包含工具调用列表
    
    返回：
    - 更新后的状态，包含工具执行结果和更新后的计数器
    """
    config = Config()
    
    if not state["tool_calls"]:
        logger.warning("No tool calls to execute")
        return update_state(state, current_step="finish")
    
    new_state = increment_call_count(state)
    
    available_tools = set(MCPClient.get_registered_tools())
    
    for tool_call in state["tool_calls"]:
        tool_name = tool_call.get("tool_name")
        method_name = tool_call.get("method_name")
        parameters = tool_call.get("parameters", {})
        
        if tool_name not in available_tools:
            logger.warning(f"LLM hallucinated non-existent tool: {tool_name}, skipping")
            new_state = add_mcp_result(new_state, {
                "tool_name": tool_name,
                "method_name": method_name,
                "parameters": parameters,
                "result": {"error": f"Tool '{tool_name}' does not exist. Available tools: {list(available_tools)}"},
            })
            continue
        
        logger.info(f"Executing MCP tool: {tool_name}.{method_name}, params: {parameters}")
        
        try:
            result = MCPClient.dispatch(
                tool_name=tool_name,
                method_name=method_name,
                parameters=parameters,
                session_id=state["session_id"],
            )
            
            logger.info(f"MCP tool executed successfully: {tool_name}.{method_name}")
            new_state = add_mcp_result(new_state, {
                "tool_name": tool_name,
                "method_name": method_name,
                "parameters": parameters,
                "result": result,
            })
            
        except Exception as e:
            logger.error(f"MCP tool execution failed: {tool_name}.{method_name}: {str(e)}", exc_info=True)
            new_state = add_mcp_result(new_state, {
                "tool_name": tool_name,
                "method_name": method_name,
                "parameters": parameters,
                "result": {"error": str(e)},
            })
    
    new_state = update_state(new_state, tool_calls=[])
    
    if new_state["call_count"] >= config.MAX_TOOL_CALLS:
        logger.info(f"Reached maximum tool call count ({config.MAX_TOOL_CALLS}), forcing finish")
        return update_state(new_state, current_step="finish")
    
    return update_state(new_state, current_step="llm_inference")


def answer_generation_node(state: AgentState) -> AgentState:
    """
    回答生成节点：整合所有信息生成最终回答。
    
    该节点的核心职责：
    1. 从长期记忆中检索相关上下文
    2. 收集 RAG 检索结果和 MCP 工具执行结果
    3. 构建包含所有上下文信息的提示词
    4. 调用 LLM 生成最终回答
    5. 将回答存入 state["final_answer"]
    6. 保存会话摘要到长期记忆
    
    如果 LLM 调用失败，会使用降级方案：
    - 返回错误提示
    - 如果有工具执行结果，附带工具返回的数据
    
    参数：
    - state: 当前代理状态，包含 RAG 结果和 MCP 结果
    
    返回：
    - 更新后的状态，包含最终回答
    """
    config = Config()
    
    model_type = state.get("model_type", "deepseek")
    image_urls = state.get("image_urls", [])
    
    if image_urls and model_type not in ("zhipu-4v",):
        model_type = "zhipu-4v"
        state = update_state(state, model_type=model_type)
    
    if model_type not in _model_cache:
        model_factory = ModelFactory()
        _model_cache[model_type] = model_factory.create_model(model_type)
        logger.info(f"Cached model for {model_type}")
    
    model = _model_cache[model_type]
    
    memory = get_memory()
    memory_context = ""
    try:
        memory_context = memory.get_relevant_context(state["user_input"], max_memories=5)
    except Exception as e:
        logger.warning(f"Failed to get memory context in answer generation: {e}")
    
    rag_results_str = json.dumps(state["rag_results"], ensure_ascii=False, indent=2) if state["rag_results"] else "[]"
    mcp_results_str = json.dumps(state["mcp_results"], ensure_ascii=False, indent=2) if state["mcp_results"] else "[]"
    
    memory_section = f"\n用户长期记忆上下文：\n{memory_context}\n" if memory_context else ""
    
    prompt = f"""
{ANSWER_GENERATION_PROMPT}
{memory_section}
用户问题：
{state['user_input']}

RAG检索结果：
{rag_results_str}

MCP工具执行结果：
{mcp_results_str}

请整合以上信息，生成最终回答。
"""
    
    user_message = {
        "role": "user",
        "content": prompt,
    }
    
    image_urls = state.get("image_urls", [])
    if image_urls:
        user_message["additional_kwargs"] = {"image_urls": image_urls}
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]
    
    chat_history = state.get("chat_history", [])
    for msg in chat_history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": content})
    
    messages.append(user_message)
    
    logger.info("Answer generation node called")
    
    try:
        response = model.invoke(messages)
        content = response.content or ""
        
        logger.info(f"Final answer generated: {content[:100]}...")
        
        rag_results = state.get("rag_results", [])
        if rag_results:
            sources_info = []
            for i, result in enumerate(rag_results[:5], 1):
                source = result.get("source", "")
                filename = result.get("metadata", {}).get("filename", "")
                kb_name = result.get("metadata", {}).get("kb_name", "")
                score = result.get("score", 0)
                
                if filename or kb_name:
                    source_desc = []
                    if kb_name:
                        source_desc.append(f"知识库:{kb_name}")
                    if filename:
                        source_desc.append(f"文档:{filename}")
                    if score > 0:
                        source_desc.append(f"相似度:{score:.2f}")
                    sources_info.append(f"[{i}] {' | '.join(source_desc)}")
            
            if sources_info:
                content += "\n\n---\n📚 **参考来源**（基于知识库检索）:\n" + "\n".join(sources_info)
        
        try:
            memory = get_memory()
            session_id = str(state.get("session_id", "unknown"))
            user_input = state.get("user_input", "")
            if content and len(content) > 10:
                memory.add_session_summary(
                    session_id=session_id,
                    summary=content[:500],
                    key_topics=[user_input[:50]] if user_input else [],
                )
                
                if state["mcp_results"]:
                    for mcp_result in state["mcp_results"][-2:]:
                        tool_name = mcp_result.get("tool_name", "")
                        result_data = mcp_result.get("result", {})
                        if isinstance(result_data, dict) and result_data.get("success"):
                            memory.add_fact_memory(
                                content=f"用户查询: {user_input[:100]}, 工具: {tool_name}, 结果摘要: {str(result_data.get('data', result_data))[:200]}",
                                importance=3,
                            )
        except Exception as e:
            logger.warning(f"Failed to save answer to memory: {e}")
        
        return update_state(
            state,
            final_answer=content,
            current_step="finish",
        )
    
    except Exception as e:
        logger.error(f"Answer generation failed: {str(e)}", exc_info=True)
        fallback_answer = "抱歉，生成回答时出错了。"
        if state["mcp_results"]:
            fallback_answer += "\n\n工具返回的数据：\n" + mcp_results_str
        return update_state(
            state,
            final_answer=fallback_answer,
            current_step="finish",
        )