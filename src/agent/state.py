from typing import TypedDict, List, Dict, Any, Optional
from uuid import UUID


class AgentState(TypedDict):
    """
    智能代理状态定义，用于 LangGraph 工作流中的状态传递。
    
    所有字段都是不可变的，通过更新函数创建新状态。
    
    字段说明：
    - user_input: 用户输入的原始问题
    - image_urls: 用户上传的图片 URL 列表（Base64 格式）
    - tool_list: 当前可用的工具列表（工具描述信息）
    - rag_results: RAG 检索返回的文档结果列表
    - mcp_results: MCP 工具调用返回的结果列表
    - chat_history: 聊天历史记录（多轮对话时使用）
    - final_answer: 最终生成的回答
    - agent_info: 代理的额外信息（如当前状态、上下文等）
    - tool_calls: LLM 决定需要调用的工具列表（包含工具名、方法名、参数）
    - current_step: 当前工作流步骤（start, tool_execution, llm_inference, finish）
    - call_count: 已调用工具的次数（用于限制最大调用次数）
    - session_id: 当前会话的 UUID（用于数据库持久化）
    - model_type: 当前使用的大模型类型（deepseek, zhipu）
    """
    user_input: str
    image_urls: List[str]
    tool_list: List[Dict[str, Any]]
    rag_results: List[Dict[str, Any]]
    mcp_results: List[Dict[str, Any]]
    chat_history: List[Dict[str, Any]]
    final_answer: str
    agent_info: Dict[str, Any]
    tool_calls: List[Dict[str, Any]]
    current_step: str
    call_count: int
    session_id: Optional[UUID]
    model_type: str


def init_state(
    user_input: str,
    session_id: Optional[UUID] = None,
    model_type: str = "deepseek",
    image_urls: Optional[List[str]] = None,
    chat_history: Optional[List[Dict[str, Any]]] = None,
) -> AgentState:
    """
    初始化智能代理状态。
    
    参数：
    - user_input: 用户输入的问题
    - session_id: 会话 UUID，用于数据库持久化
    - model_type: 大模型类型，默认 deepseek
    - image_urls: 用户上传的图片 URL 列表（Base64 格式）
    - chat_history: 历史对话记录，用于上下文记忆
    
    返回：
    - 初始化后的 AgentState 对象
    """
    return {
        "user_input": user_input,
        "image_urls": image_urls or [],
        "tool_list": [],
        "rag_results": [],
        "mcp_results": [],
        "chat_history": chat_history or [],
        "final_answer": "",
        "agent_info": {},
        "tool_calls": [],
        "current_step": "start",
        "call_count": 0,
        "session_id": session_id,
        "model_type": model_type,
    }


def update_state(
    state: AgentState,
    **updates: Any,
) -> AgentState:
    """
    更新代理状态，返回新状态对象（不可变更新）。
    
    参数：
    - state: 原始状态对象
    - **updates: 需要更新的字段键值对
    
    返回：
    - 新的 AgentState 对象，包含原始字段和更新的字段
    """
    return {**state, **updates}


def add_mcp_result(state: AgentState, result: Dict[str, Any]) -> AgentState:
    """
    向状态中添加 MCP 工具调用结果。
    
    参数：
    - state: 当前状态对象
    - result: MCP 工具调用结果字典
    
    返回：
    - 新状态，mcp_results 列表包含新增的结果
    """
    new_results = state["mcp_results"] + [result]
    return update_state(state, mcp_results=new_results)


def add_rag_result(state: AgentState, results: List[Dict[str, Any]]) -> AgentState:
    """
    向状态中添加 RAG 检索结果。
    
    参数：
    - state: 当前状态对象
    - results: RAG 检索结果列表
    
    返回：
    - 新状态，rag_results 列表包含新增的结果
    """
    new_results = state["rag_results"] + results
    return update_state(state, rag_results=new_results)


def increment_call_count(state: AgentState) -> AgentState:
    """
    增加工具调用计数器。
    
    参数：
    - state: 当前状态对象
    
    返回：
    - 新状态，call_count 增加 1
    """
    return update_state(state, call_count=state["call_count"] + 1)