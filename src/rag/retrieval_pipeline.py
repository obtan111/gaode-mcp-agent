"""
RAG 检索管道模块。

该模块实现了完整的三级检索架构：
1. 第一级：多路径并行检索（DenseRetriever + BM25Retriever）
2. 第二级：RRF 融合排序（Reciprocal Rank Fusion）
3. 第三级：Cross-Encoder 精排（相关性重排序）

核心类：
- RetrievalResult: 检索结果数据结构
- DenseRetriever: 密集向量检索器（语义检索）
- BM25Retriever: 关键词检索器（字面匹配）
- RRFFusion: RRF 融合排序器
- CrossEncoderReranker: Cross-Encoder 精排器
- RetrievalPipeline: 检索管道主类，整合所有组件
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from collections import defaultdict
import hashlib

from src.config import Config
from src.database.crud import search_documents_by_vector, search_documents_by_keyword
from src.llm.embedding import EmbeddingFactory
from src.utils.logger import setup_logger

logger = setup_logger("retrieval_pipeline")


@dataclass
class RetrievalResult:
    """
    检索结果数据结构。
    
    属性：
    - id: 文档 ID
    - content: 文档内容
    - score: 相关性分数（不同阶段含义不同：向量相似度/RRF分数/Cross-Encoder分数）
    - rank: 当前排名
    - source: 来源标识（dense/bm25/rrf/rerank）
    - metadata: 文档元数据（文件名、页码、分类等）
    """
    id: str
    content: str
    score: float
    rank: int
    source: str
    metadata: Optional[Dict[str, Any]] = None


class DenseRetriever:
    """
    密集向量检索器。
    
    基于嵌入模型将查询转换为向量，通过余弦相似度匹配文档。
    优势：理解语义，能匹配同义词、近义词（如"故宫"和"紫禁城"）。
    
    属性：
    - config: 配置对象
    - embedding_factory: 嵌入模型工厂
    - embedding: 嵌入模型实例
    """
    def __init__(self, embedding_type: str = "deepseek", model_name: Optional[str] = None):
        """
        初始化密集向量检索器。
        
        参数：
        - embedding_type: 嵌入模型类型（默认 deepseek）
        - model_name: 嵌入模型名称（可选）
        """
        self.config = Config()
        self.embedding_factory = EmbeddingFactory()
        self.embedding = self.embedding_factory.create_embedding(embedding_type, model_name)

    def retrieve(self, query: str, top_k: int = 10, kb_name: Optional[str] = None) -> List[RetrievalResult]:
        """
        执行密集向量检索。
        
        流程：
        1. 将查询文本转换为向量
        2. 调用数据库向量检索（pgvector 或客户端计算）
        3. 构建 RetrievalResult 列表
        
        参数：
        - query: 用户查询文本
        - top_k: 返回结果数量（默认 10）
        - kb_name: 知识库名称（可选，为空则检索所有知识库）
        
        返回：
        - RetrievalResult 列表，按相似度降序排列
        """
        logger.info(f"DenseRetriever retrieving for query: {query[:50]}..., top_k: {top_k}")
        
        # 1. 将查询转换为向量（捕获嵌入失败异常）
        try:
            query_vector = self.embedding.embed_query(query)
        except Exception as e:
            logger.error(f"Embedding failed: {str(e)}")
            return []
        
        # 2. 调用数据库向量检索
        try:
            results = search_documents_by_vector(
                query_vector=query_vector,
                limit=top_k,
                kb_name=kb_name,
            )
        except Exception as e:
            logger.error(f"Vector search failed: {str(e)}")
            return []
        
        # 3. 构建检索结果列表
        retrieval_results = []
        for rank, doc in enumerate(results, start=1):
            retrieval_results.append(RetrievalResult(
                id=str(doc.get("id")),
                content=doc.get("content", ""),
                score=doc.get("similarity", 0.0),  # 余弦相似度分数
                rank=rank,
                source="dense",  # 标识来源为密集向量检索
                metadata=doc.get("metadata"),
            ))
        
        logger.info(f"DenseRetriever found {len(retrieval_results)} results")
        return retrieval_results


class BM25Retriever:
    """
    关键词检索器（BM25 风格）。
    
    使用 PostgreSQL 的 ILIKE 进行模糊匹配，实现关键词精确检索。
    优势：精确匹配关键词，对专有名词、人名、地名效果好。
    
    属性：
    - config: 配置对象
    """
    def __init__(self):
        """初始化关键词检索器"""
        self.config = Config()

    def retrieve(self, query: str, top_k: int = 10, kb_name: Optional[str] = None) -> List[RetrievalResult]:
        """
        执行关键词检索。
        
        流程：
        1. 使用 SQL ILIKE 进行模糊匹配
        2. 计算分数（1/rank，排名越靠前分数越高）
        3. 构建 RetrievalResult 列表
        
        参数：
        - query: 用户查询文本
        - top_k: 返回结果数量（默认 10）
        - kb_name: 知识库名称（可选，为空则检索所有知识库）
        
        返回：
        - RetrievalResult 列表，按匹配度降序排列
        """
        logger.info(f"BM25Retriever retrieving for query: {query[:50]}..., top_k: {top_k}")
        
        # 1. 调用数据库关键词检索（ILIKE 模糊匹配）
        results = search_documents_by_keyword(
            keyword=query,
            limit=top_k,
            kb_name=kb_name,
        )
        
        # 2. 构建检索结果列表，分数 = 1/rank
        retrieval_results = []
        for rank, doc in enumerate(results, start=1):
            score = 1.0 / rank  # 排名越靠前分数越高（1, 0.5, 0.33, ...）
            retrieval_results.append(RetrievalResult(
                id=str(doc.get("id")),
                content=doc.get("content", ""),
                score=score,
                rank=rank,
                source="bm25",  # 标识来源为关键词检索
                metadata=doc.get("metadata"),
            ))
        
        logger.info(f"BM25Retriever found {len(retrieval_results)} results")
        return retrieval_results


class RRFFusion:
    """
    RRF 融合排序器（Reciprocal Rank Fusion）。
    
    RRF 是一种经典的融合算法，用于整合多个检索器的结果。
    公式：RRF(d) = Σ(1/(k + rank_i(d)))
    
    设计原理：
    - 如果一个文档在多个检索器中都排名靠前，它的 RRF 分数会显著更高
    - 避免单一检索器的局限性，融合语义检索和关键词检索的优势
    
    属性：
    - k: 超参数（默认 60），控制排名对分数的影响程度
    """
    def __init__(self, k: int = 60):
        """
        初始化 RRF 融合器。
        
        参数：
        - k: 超参数（默认 60），值越小排名对分数影响越大
        """
        self.k = k
        logger.info(f"RRFFusion initialized with k={k}")

    def fuse(self, results_list: List[List[RetrievalResult]]) -> List[RetrievalResult]:
        """
        融合多个检索器的结果列表。
        
        流程：
        1. 遍历每个检索器的结果
        2. 对每个文档计算 RRF 分数：1/(k + rank)
        3. 累加所有检索器的分数
        4. 按总分排序，重新分配排名
        
        参数：
        - results_list: 多个检索器的结果列表（如 [dense_results, bm25_results]）
        
        返回：
        - 融合后的 RetrievalResult 列表，按 RRF 分数降序排列
        """
        logger.info(f"RRFFusion fusing {len(results_list)} result lists")
        
        scores = defaultdict(float)  # 存储每个文档的 RRF 分数
        doc_map = {}                 # 存储文档详情（避免重复存储）
        
        # 遍历每个检索器的结果
        for results in results_list:
            for rank, result in enumerate(results, start=1):
                # 计算 RRF 分数：1/(k + rank)
                rrf_score = 1.0 / (self.k + rank)
                scores[result.id] += rrf_score  # 累加到总分
                
                # 存储文档详情（只存储一次）
                if result.id not in doc_map:
                    doc_map[result.id] = result
        
        # 构建融合结果列表
        fused_results = []
        for doc_id, total_score in scores.items():
            original = doc_map[doc_id]
            fused_results.append(RetrievalResult(
                id=doc_id,
                content=original.content,
                score=total_score,       # RRF 总分
                rank=0,                  # 排名待分配
                source=f"rrf({original.source})",  # 标识来源
                metadata=original.metadata,
            ))
        
        # 按 RRF 分数降序排序
        fused_results.sort(key=lambda x: x.score, reverse=True)
        
        # 重新分配排名
        for idx, result in enumerate(fused_results, start=1):
            result.rank = idx
        
        logger.info(f"RRFFusion completed, {len(fused_results)} results")
        return fused_results


class CrossEncoderReranker:
    """
    Cross-Encoder 精排器。
    
    使用 cross-encoder 模型对文档进行精排，基于 (query, document) 对预测相关性。
    相比 Bi-Encoder（向量检索），Cross-Encoder 可以看到 query 和 document 的交互信息，
    相关性判断更准确，但计算成本更高。
    
    模型选择：cross-encoder/ms-marco-MiniLM-L-6-v2
    - 基于 MS MARCO 数据集训练
    - 专门优化问答场景的相关性判断
    - 模型小巧（MiniLM-L-6），推理速度快
    
    属性：
    - model_name: 模型名称
    - _model: 模型实例（延迟加载）
    """
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        """
        初始化 Cross-Encoder 精排器。
        
        参数：
        - model_name: cross-encoder 模型名称（默认 ms-marco-MiniLM-L-6-v2）
        """
        self.model_name = model_name
        self._model = None  # 延迟加载
        logger.info(f"CrossEncoderReranker initialized with model: {model_name}")

    def _get_model(self):
        """
        获取 cross-encoder 模型实例（延迟加载）。
        
        首次调用时加载模型，之后复用。
        如果 sentence_transformers 不可用，返回 None（降级到轻量级方案）。
        
        返回：
        - CrossEncoder 模型实例，或 None（使用轻量级精排）
        """
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
                self._model = CrossEncoder(self.model_name)
                logger.info(f"CrossEncoder model loaded: {self.model_name}")
            except (ImportError, Exception) as e:
                logger.warning(f"CrossEncoder not available ({type(e).__name__}), using lightweight reranker")
                return None
        return self._model

    def _lightweight_score(self, query: str, document: str) -> float:
        """
        轻量级相关性分数计算（不依赖深度学习模型）。
        
        基于以下特征计算相关性分数（范围 [0, 1]）：
        1. 关键词覆盖率：query 中的词在 document 中出现的比例
        2. 字符 Jaccard 相似度
        3. 短语匹配：query 是否作为子串出现
        4. 位置加权：query 词在文档中出现的位置
        
        参数：
        - query: 用户查询
        - document: 文档内容
        
        返回：
        - 相关性分数 [0, 1]
        """
        import re
        
        # 中文分词：按字符和英文单词分割
        query_tokens = set(re.findall(r'[\u4e00-\u9fff]|[a-zA-Z]+', query.lower()))
        doc_tokens = set(re.findall(r'[\u4e00-\u9fff]|[a-zA-Z]+', document.lower()))
        
        if not query_tokens:
            return 0.0
        
        # 1. 关键词覆盖率
        covered = query_tokens & doc_tokens
        coverage_score = len(covered) / len(query_tokens)
        
        # 2. Jaccard 相似度
        intersection = query_tokens & doc_tokens
        union = query_tokens | doc_tokens
        jaccard_score = len(intersection) / len(union) if union else 0.0
        
        # 3. 短语匹配
        phrase_score = 1.0 if query.lower() in document.lower() else 0.0
        
        # 4. 位置加权
        position_scores = []
        for token in query_tokens:
            idx = document.lower().find(token)
            if idx >= 0:
                pos_score = max(0, 1.0 - idx / max(len(document), 1))
                position_scores.append(pos_score)
            else:
                position_scores.append(0.0)
        position_score = sum(position_scores) / len(position_scores) if position_scores else 0.0
        
        # 加权融合：覆盖率 40% + Jaccard 20% + 短语 20% + 位置 20%
        final_score = (
            0.4 * coverage_score + 
            0.2 * jaccard_score + 
            0.2 * phrase_score + 
            0.2 * position_score
        )
        
        return max(0.0, min(1.0, final_score))

    def rerank(self, query: str, results: List[RetrievalResult], top_n: int = 5) -> List[RetrievalResult]:
        """
        对检索结果进行精排。
        
        流程：
        1. 获取精排器（Cross-Encoder 模型或轻量级方案）
        2. 计算每个 (query, document) 对的相关性分数
        3. 按分数排序，重新分配排名
        4. 返回 top_n 结果
        
        参数：
        - query: 用户查询文本
        - results: 待重排的检索结果列表（通常是 RRF 融合后的结果）
        - top_n: 返回结果数量（默认 5）
        
        返回：
        - 精排后的 RetrievalResult 列表，按相关性分数降序排列
        """
        logger.info(f"CrossEncoderReranker reranking {len(results)} results for query: {query[:50]}...")
        
        # 1. 获取精排方式
        model = self._get_model()
        use_cross_encoder = model is not None
        
        # 2. 计算分数
        if use_cross_encoder:
            # 使用 Cross-Encoder 模型
            pairs = [(query, result.content) for result in results]
            scores = model.predict(pairs)
            source_prefix = "rerank"
        else:
            # 使用轻量级方案
            scores = [self._lightweight_score(query, result.content) for result in results]
            source_prefix = "lightweight_rerank"
        
        # 3. 构建精排结果列表
        scored_results = []
        for result, score in zip(results, scores):
            scored_results.append(RetrievalResult(
                id=result.id,
                content=result.content,
                score=score,
                rank=0,
                source=f"{source_prefix}({result.source})",
                metadata=result.metadata,
            ))
        
        # 4. 按分数降序排序
        scored_results.sort(key=lambda x: x.score, reverse=True)
        
        # 5. 重新分配排名
        for idx, result in enumerate(scored_results, start=1):
            result.rank = idx
        
        # 6. 返回 top_n 结果
        final_results = scored_results[:top_n]
        logger.info(
            f"CrossEncoderReranker completed, {len(final_results)} results, "
            f"using {'cross-encoder' if use_cross_encoder else 'lightweight'} scorer"
        )
        return final_results


class RetrievalPipeline:
    """
    RAG 检索管道主类。
    
    整合三级检索架构：
    1. 第一级：多路径并行检索（DenseRetriever + BM25Retriever）
    2. 第二级：RRF 融合排序（RRFFusion）
    3. 第三级：Cross-Encoder 精排（CrossEncoderReranker）
    
    属性：
    - top_k: 每个检索器返回的结果数量
    - rrf_k: RRF 融合的 k 值
    - rerank_top_n: 精排后返回的结果数量
    - score_threshold: Cross-Encoder 分数阈值
    - max_text_length: 返回文本的最大长度
    - dense_retriever: 密集向量检索器
    - bm25_retriever: 关键词检索器
    - rrf_fusion: RRF 融合排序器
    - reranker: Cross-Encoder 精排器
    """
    def __init__(
        self,
        top_k: Optional[int] = None,
        rrf_k: Optional[int] = None,
        rerank_top_n: Optional[int] = None,
        score_threshold: Optional[float] = None,
        max_text_length: Optional[int] = None,
        embedding_type: str = "zhipu",
        embedding_model: Optional[str] = None,
        cross_encoder_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
    ):
        """
        初始化检索管道。
        
        参数：
        - top_k: 每个检索器返回的结果数量（默认从配置读取）
        - rrf_k: RRF 融合的 k 值（默认从配置读取）
        - rerank_top_n: 精排后返回的结果数量（默认从配置读取）
        - score_threshold: Cross-Encoder 分数阈值（默认从配置读取）
        - max_text_length: 返回文本的最大长度（默认 2000）
        - embedding_type: 嵌入模型类型（默认 deepseek）
        - embedding_model: 嵌入模型名称（可选）
        - cross_encoder_model: cross-encoder 模型名称（默认 ms-marco-MiniLM-L-6-v2）
        """
        self.config = Config()
        
        # 配置参数（优先使用传入值，否则使用配置默认值）
        self.top_k = top_k or self.config.RETRIEVE_TOP_K
        self.rrf_k = rrf_k or self.config.RRF_K
        self.rerank_top_n = rerank_top_n or self.config.RETRIEVE_TOP_K
        self.score_threshold = score_threshold or self.config.CROSS_ENCODER_THRESHOLD
        self.max_text_length = max_text_length or self.config.MAX_TEXT_LENGTH
        
        # 初始化检索组件
        self.dense_retriever = DenseRetriever(embedding_type, embedding_model)
        self.bm25_retriever = BM25Retriever()
        self.rrf_fusion = RRFFusion(k=self.rrf_k)
        self.reranker = CrossEncoderReranker(model_name=cross_encoder_model)
        
        logger.info(
            f"RetrievalPipeline initialized: "
            f"top_k={self.top_k}, rrf_k={self.rrf_k}, "
            f"rerank_top_n={self.rerank_top_n}, score_threshold={self.score_threshold}, "
            f"max_text_length={self.max_text_length}"
        )

    def _truncate_text(self, content: str) -> str:
        """
        截断文本到最大长度。
        
        参数：
        - content: 原始文本
        
        返回：
        - 截断后的文本（末尾添加 "..." 如果被截断）
        """
        if len(content) <= self.max_text_length:
            return content
        return content[:self.max_text_length] + "..."

    def retrieve(self, query: str, kb_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        执行完整的检索流程。
        
        流程：
        1. 多路径并行检索（DenseRetriever + BM25Retriever）
        2. RRF 融合排序
        3. Cross-Encoder 精排
        4. 阈值过滤
        5. 文本截断和格式化
        
        参数：
        - query: 用户查询文本
        - kb_name: 知识库名称（可选，为空则检索所有知识库）
        
        返回：
        - 最终检索结果列表，包含 id、content、score、rank、source、metadata
        """
        logger.info(f"RetrievalPipeline starting for query: {query[:50]}...")
        
        # 1. 第一级：多路径并行检索
        dense_results = self.dense_retriever.retrieve(query, self.top_k, kb_name)
        bm25_results = self.bm25_retriever.retrieve(query, self.top_k, kb_name)
        
        # 2. 第二级：RRF 融合排序
        fused_results = self.rrf_fusion.fuse([dense_results, bm25_results])
        
        # 3. 第三级：Cross-Encoder 精排
        reranked_results = self.reranker.rerank(query, fused_results, self.rerank_top_n)
        
        # 4. 阈值过滤（只保留分数超过阈值的结果）
        # 精排后的分数范围是 [0, 1]，始终应用阈值过滤
        filtered_results = [
            r for r in reranked_results 
            if r.score >= self.score_threshold
        ]
        
        # 5. 去重（基于内容hash，避免同一内容重复出现）
        seen_hashes = set()
        deduplicated_results = []
        for result in filtered_results:
            content_hash = hashlib.md5(result.content.encode("utf-8")).hexdigest()
            if content_hash not in seen_hashes:
                seen_hashes.add(content_hash)
                deduplicated_results.append(result)
        
        logger.info(f"Deduplication: {len(filtered_results)} -> {len(deduplicated_results)} results")
        
        # 6. 文本截断和格式化
        final_results = []
        for result in deduplicated_results:
            final_results.append({
                "id": result.id,
                "content": self._truncate_text(result.content),  # 截断过长文本
                "score": round(result.score, 4),                 # 保留 4 位小数
                "rank": result.rank,
                "source": result.source,                         # 标识来源
                "metadata": result.metadata,                     # 元数据
            })
        
        logger.info(f"RetrievalPipeline completed, {len(final_results)} final results")
        return final_results