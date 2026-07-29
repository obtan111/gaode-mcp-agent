from typing import Optional, List, Dict, Any

from src.mcp.mcp_client import MCPClient
from src.rag.retrieval_pipeline import RetrievalPipeline
from src.utils.logger import setup_logger
from src.utils.retry import retry

logger = setup_logger("rag_mcp")


_pipeline_cache = {}

@MCPClient.register_tool("RagMCP")
class RagMCP(MCPClient):
    def __init__(self):
        super().__init__()
        self.retrieval_pipeline = RetrievalPipeline()

    @retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0)
    def search_knowledge(self, query: str, kb_name: Optional[str] = None, top_k: Optional[int] = None) -> dict:
        """
        多路混合检索私有知识库
        
        使用多路混合检索（Dense Retrieval + BM25 + RRF Fusion + Cross-Encoder Reranking）
        从私有知识库中检索与查询相关的文档片段。
        
        Args:
            query: 用户查询语句，如 "北京故宫的历史"、"上海迪士尼门票价格"
            kb_name: 知识库名称，用于限定检索范围。如果不提供，则检索所有知识库。
            top_k: 返回结果数量，默认为配置文件中的 RETRIEVE_TOP_K 值。
        
        Returns:
            dict: 包含检索结果的字典：
                - success: 是否检索成功
                - query: 用户查询语句
                - kb_name: 使用的知识库名称（如果有）
                - total_results: 返回结果总数
                - results: 文档片段列表，每个元素包含：
                    - id: 文档唯一标识
                    - content: 文档内容片段
                    - score: 相关性分数（越高越相关）
                    - rank: 排名（从1开始）
                    - source: 检索来源（如 "rerank(dense)"、"rerank(bm25)"）
                    - metadata: 文档元数据，可能包含：
                        - filename: 原始文件名
                        - page_number: 页码
                        - category: 分类
                        - url: 来源URL
        """
        logger.info(f"search_knowledge called, query={query[:50]}..., kb_name={kb_name}, top_k={top_k}")
        
        try:
            cache_key = str(top_k) if top_k else "default"
            if cache_key not in _pipeline_cache:
                _pipeline_cache[cache_key] = RetrievalPipeline(top_k=top_k)
                logger.info(f"Cached RetrievalPipeline for top_k={top_k}")
            
            pipeline = _pipeline_cache[cache_key]
            results = pipeline.retrieve(query, kb_name)
            
            result = {
                "success": True,
                "query": query,
                "kb_name": kb_name,
                "total_results": len(results),
                "results": results,
            }
            
            logger.info(f"search_knowledge succeeded, found {len(results)} results")
            return result
            
        except Exception as e:
            logger.error(f"search_knowledge failed: {e}")
            return {
                "success": False,
                "query": query,
                "kb_name": kb_name,
                "total_results": 0,
                "results": [],
                "error": str(e),
            }