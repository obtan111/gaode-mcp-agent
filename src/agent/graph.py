from langgraph.graph import StateGraph, END
from typing import Dict, Any, Callable, Optional, List

from src.config import Config
from src.agent.state import AgentState, init_state
from src.agent.nodes import llm_inference_node, mcp_execution_node, answer_generation_node
from src.agent.memory import get_memory
from src.utils.logger import setup_logger

logger = setup_logger("agent_graph")


def should_call_tool(state: AgentState) -> str:
    """
    条件分支函数：判断是否需要调用工具。
    
    根据 LLM 的推理结果决定下一步：
    - 如果 state["current_step"] 为 "finish"，直接结束
    - 如果 state["tool_calls"] 不为空，说明 LLM 需要调用工具
    - 否则直接进入回答生成阶段
    
    参数：
    - state: 当前代理状态
    
    返回：
    - "tool_execution": 需要调用工具
    - "answer_generation": 直接生成回答
    - "end": 已经完成，直接结束
    """
    if state["current_step"] == "finish":
        return "end"
    if state["tool_calls"] and len(state["tool_calls"]) > 0:
        return "tool_execution"
    return "answer_generation"


def should_end(state: AgentState) -> str:
    """
    条件分支函数：判断是否应该结束工作流（工具执行后调用）。
    
    判断条件：
    1. 如果当前步骤为 "finish"，直接结束
    2. 如果工具调用次数达到上限，进入回答生成
    3. 如果有工具执行结果但没有新的工具调用，进入回答生成
    4. 如果还有待执行的工具调用，继续推理
    
    参数：
    - state: 当前代理状态
    
    返回：
    - "end": 结束工作流
    - "llm_inference": 继续推理（还有新工具调用）
    - "answer_generation": 生成最终回答（工具执行完成）
    """
    config = Config()
    
    if state["current_step"] == "finish":
        return "end"
    
    if state["call_count"] >= config.MAX_TOOL_CALLS:
        return "answer_generation"
    
    if state["mcp_results"] and not state["tool_calls"]:
        return "answer_generation"
    
    if state["tool_calls"]:
        return "llm_inference"
    
    return "answer_generation"


class AgentGraph:
    """
    智能代理工作流图，基于 LangGraph 构建。
    
    工作流包含三个核心节点：
    1. llm_inference: LLM 推理节点，识别用户意图并决定是否调用工具
    2. tool_execution: MCP 工具执行节点，执行外部工具调用
    3. answer_generation: 回答生成节点，整合所有信息生成最终回答
    
    工作流逻辑：
    - 入口 → llm_inference → 判断是否调用工具
    - 如果需要调用工具 → tool_execution → 判断是否结束
    - 如果结束 → END；否则 → llm_inference（循环）
    - 如果不需要调用工具 → answer_generation → END
    """
    
    def __init__(self):
        """初始化代理图，构建工作流结构"""
        self.config = Config()
        self.graph = self._build_graph()
        self._compiled_graph = None
    
    def _build_graph(self) -> StateGraph:
        """
        构建 LangGraph 工作流图。
        
        创建三个节点并定义它们之间的连接关系：
        - llm_inference: 入口节点，负责意图识别和工具选择
        - tool_execution: 条件分支节点，执行工具调用
        - answer_generation: 结束节点，生成最终回答
        
        返回：
        - 构建好的 StateGraph 对象
        """
        workflow = StateGraph(AgentState)
        
        # 添加三个核心节点
        workflow.add_node("llm_inference", llm_inference_node)
        workflow.add_node("tool_execution", mcp_execution_node)
        workflow.add_node("answer_generation", answer_generation_node)
        
        # 设置入口点为 LLM 推理
        workflow.set_entry_point("llm_inference")
        
        # LLM 推理后的条件分支：调用工具、直接回答或结束
        workflow.add_conditional_edges(
            "llm_inference",
            should_call_tool,
            {
                "tool_execution": "tool_execution",
                "answer_generation": "answer_generation",
                "end": END,
            },
        )
        
        # 工具执行后的条件分支：继续推理、生成回答或结束
        workflow.add_conditional_edges(
            "tool_execution",
            should_end,
            {
                "llm_inference": "llm_inference",
                "answer_generation": "answer_generation",
                "end": END,
            },
        )
        
        # 回答生成后直接结束
        workflow.add_edge("answer_generation", END)
        
        return workflow
    
    def compile(self, force_recompile: bool = False) -> Callable:
        """
        编译工作流图，生成可执行函数（缓存结果）。
        
        参数：
        - force_recompile: 是否强制重新编译（修改图结构后需要）
        
        返回：
        - 编译后的工作流调用函数
        """
        if force_recompile or self._compiled_graph is None:
            self._compiled_graph = self.graph.compile()
            logger.info("Agent graph compiled successfully")
        return self._compiled_graph
    
    def run(
        self,
        user_input: str,
        session_id: Any = None,
        model_type: str = "deepseek",
        image_urls: Optional[List[str]] = None,
        chat_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        运行代理工作流，处理用户输入。
        
        集成长期记忆系统：
        1. 初始化长期记忆实例
        2. 从记忆中检索相关上下文（由节点内部完成）
        3. 工作流结束后保存会话摘要和用户画像
        4. 自动提取用户事实和偏好
        
        参数：
        - user_input: 用户输入的问题
        - session_id: 会话 UUID，用于数据库持久化和工具调用日志
        - model_type: 大模型类型（deepseek 或 zhipu）
        - image_urls: 用户上传的图片 URL 列表（Base64 格式）
        - chat_history: 历史对话记录，用于多轮上下文记忆
        
        返回：
        - 包含最终回答和相关信息的字典
        """
        initial_state = init_state(user_input, session_id, model_type, image_urls, chat_history)
        compiled_graph = self.compile()
        
        memory = get_memory()
        session_id_str = str(session_id) if session_id else f"session_{id(initial_state)}"
        
        logger.info(f"Starting agent workflow for input: {user_input[:50]}... (model: {model_type})")
        
        try:
            result = compiled_graph.invoke(initial_state)
            logger.info("Agent workflow completed successfully")
            
            try:
                self._post_session_cleanup(
                    memory=memory,
                    user_input=user_input,
                    result=result,
                    session_id=session_id_str,
                )
            except Exception as e:
                logger.warning(f"Post-session memory save failed: {e}")
            
            return result
        except Exception as e:
            logger.error(f"Agent workflow failed: {str(e)}", exc_info=True)
            
            try:
                memory = get_memory()
                memory.add_session_summary(
                    session_id=session_id_str,
                    summary=f"[工作流异常] 用户输入: {user_input[:200]}, 错误: {str(e)[:200]}",
                    key_topics=[user_input[:50]],
                )
            except Exception:
                pass
            
            return {
                "user_input": user_input,
                "final_answer": f"抱歉，处理您的请求时出错：{str(e)}",
                "error": str(e),
            }
    
    def _post_session_cleanup(
        self,
        memory,
        user_input: str,
        result: Dict[str, Any],
        session_id: str,
    ) -> None:
        """
        会话结束后的记忆清理和保存工作。
        
        职责：
        1. 保存会话摘要（如果节点内未保存）
        2. 提取用户画像信息
        3. 定期清理过期记忆
        
        参数：
        - memory: LongTermMemory 实例
        - user_input: 用户原始输入
        - result: 工作流最终结果
        - session_id: 会话 ID
        """
        final_answer = result.get("final_answer", "")
        
        if final_answer and len(final_answer) > 20:
            existing = memory.search_memories(
                query=session_id,
                memory_type="summary",
                limit=1,
            )
            if not existing:
                memory.add_session_summary(
                    session_id=session_id,
                    summary=final_answer[:500],
                    key_topics=[user_input[:50]] if user_input else [],
                )
        
        self._try_extract_user_profile(memory, user_input, final_answer)
        
        import random
        if random.random() < 0.1:
            memory.cleanup_expired(max_facts=100)
    
    def _try_extract_user_profile(
        self,
        memory,
        user_input: str,
        final_answer: str,
    ) -> None:
        """
        尝试从对话中提取用户画像信息。
        
        提取规则：
        - 检测用户提到的姓名、职业、偏好等
        - 使用简单的关键词匹配规则
        - 避免过度提取（只提取明确声明的信息）
        
        参数：
        - memory: LongTermMemory 实例
        - user_input: 用户原始输入
        - final_answer: 最终回答
        """
        combined = f"{user_input} {final_answer}"
        
        profile_extractions = [
            (["我叫", "我是", "我的名字", "我名字是"], "name"),
            (["我是", "我从事", "我的职业", "我在"], "occupation"),
            (["我住在", "我在", "我居住", "城市是"], "location"),
            (["我喜欢", "我偏爱", "我倾向", "我爱好"], "preference_hint"),
        ]
        
        for keywords, field in profile_extractions:
            for kw in keywords:
                if kw in user_input:
                    try:
                        memory.update_user_profile(
                            **{f"detected_{field}": f"用户提到: {kw}"}
                        )
                    except Exception:
                        pass
                    break