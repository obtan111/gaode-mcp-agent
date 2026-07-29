"""
RAG 评估模块。

提供 RAG 管道的质量评估工具，包括：
- 忠实度（Faithfulness）：回答是否基于检索到的上下文
- 答案相关性（Answer Relevancy）：回答是否与问题相关
- 上下文精确度（Context Precision）：检索结果是否精准
- 上下文召回率（Context Recall）：是否检索到了所有必要信息
"""

from .ragas_evaluator import RAGEvaluator, EvaluationResult, evaluate_rag_pipeline

__all__ = [
    "RAGEvaluator",
    "EvaluationResult",
    "evaluate_rag_pipeline",
]
