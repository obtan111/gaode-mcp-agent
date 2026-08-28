"""知识库路由：文档上传并向量化、内容查看、删除与检索调试。"""

import json
import os
import time
import uuid
from typing import Dict, List, Tuple

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.schemas.kb import RetrieveRequest, RetrieveResponse
from src.config.settings import Config
from src.database.crud import (
    delete_documents_by_filename,
    get_document_by_id,
    get_documents_by_kb,
    get_knowledge_base_names,
    insert_document,
)
from src.rag.document_parser import DocumentParserFactory
from src.rag.retrieval_pipeline import RetrievalPipeline
from src.rag.text_splitter import TextSplitter
from src.utils.file_utils import is_file_size_valid
from src.utils.logger import setup_logger

logger = setup_logger("kb_router")

router = APIRouter(prefix="/api/kb", tags=["knowledge-base"])

MAX_FILE_SIZE_MB = 50
ALLOWED_EXTENSIONS = {"txt", "md", "markdown", "pdf", "json", "csv"}

_text_splitter = None


def _get_splitter() -> TextSplitter:
    global _text_splitter
    if _text_splitter is None:
        from backend.core.deps import get_embedding_factory

        _text_splitter = TextSplitter(Config())
    return _text_splitter


@router.get("")
def read_kbs():
    return get_knowledge_base_names()


_DOC_COLUMNS = "id, filename, page_number, category, kb_name, created_at"
_DETAIL_COLUMNS = "id, filename, content, page_number, category, metadata, kb_name, created_at"
_LIST_PREVIEW_CHARS = 300

# 列表 TTL 缓存：跨海链路往返约 1.5 秒，缓存让反复查看/切换知识库秒开。
# 载荷本身已降到 KB 级，缓存主要吸收网络 RTT；上传/删除时主动失效。
_LIST_CACHE: Dict[str, Tuple[float, list]] = {}
_LIST_CACHE_TTL = 30.0


def _invalidate_list_cache(kb_name: str) -> None:
    _LIST_CACHE.pop(kb_name, None)


def _strip_embedding_vector(doc: dict) -> dict:
    """剔除 metadata 里重复存放的向量（约 22KB/行），列表与详情都不需要它。"""
    metadata = doc.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop("embedding_vector", None)
    elif isinstance(metadata, str):
        try:
            parsed = json.loads(metadata)
            if isinstance(parsed, dict):
                parsed.pop("embedding_vector", None)
                doc["metadata"] = parsed
        except (ValueError, TypeError):
            pass
    return doc


@router.get("/{kb_name}/documents")
def read_documents(kb_name: str):
    """返回知识库分片列表。

    列表接口保持轻量：不拉 metadata（内含 22KB/行的向量副本），
    内容截断为前 300 字预览并附 content_len 总长；
    完整内容由 GET /api/kb/documents/{id} 按需加载。
    """
    now = time.time()
    cached = _LIST_CACHE.get(kb_name)
    if cached and cached[0] > now:
        return cached[1]

    docs = get_documents_by_kb(kb_name, columns=_DOC_COLUMNS)
    for doc in docs:
        content = doc.get("content") or ""
        doc["content_len"] = len(content)
        doc["content"] = content[:_LIST_PREVIEW_CHARS]
    _LIST_CACHE[kb_name] = (now + _LIST_CACHE_TTL, docs)
    return docs


@router.get("/documents/{doc_id}")
def read_document(doc_id: str):
    """按 ID 返回单个分片完整内容（详情弹窗用）。"""
    try:
        uid = uuid.UUID(doc_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的文档 ID")
    doc = get_document_by_id(uid, columns=_DETAIL_COLUMNS)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    return _strip_embedding_vector(doc)


@router.delete("/{kb_name}")
def remove_kb(kb_name: str):
    _invalidate_list_cache(kb_name)
    docs = get_documents_by_kb(kb_name, columns="filename")
    filenames = {doc.get("filename", "") for doc in docs} - {""}
    deleted_chunks = sum(delete_documents_by_filename(name) or 0 for name in filenames)
    logger.info(f"Deleted KB '{kb_name}': {deleted_chunks} chunks")
    return {"ok": True, "deleted_chunks": deleted_chunks}


@router.post("/{kb_name}/documents")
async def upload_documents(kb_name: str, files: List[UploadFile] = File(...)):
    """上传文档并完成 解析 → 切分 → 向量化 → 入库 全流程。"""
    from backend.core.deps import get_embedding_factory

    embedding = get_embedding_factory().create_embedding("zhipu")
    _invalidate_list_cache(kb_name)
    success_count = 0
    fail_count = 0
    failures: List[str] = []

    for file in files:
        filename = file.filename or "未命名文件"
        ext = os.path.splitext(filename)[1].lstrip(".").lower()
        try:
            content_bytes = await file.read()
        finally:
            await file.close()

        if ext not in ALLOWED_EXTENSIONS:
            fail_count += 1
            failures.append(f"{filename}: 不支持的类型 '{ext}'")
            continue
        if not content_bytes:
            fail_count += 1
            failures.append(f"{filename}: 文件为空")
            continue
        if not is_file_size_valid(content_bytes, MAX_FILE_SIZE_MB * 1024 * 1024):
            fail_count += 1
            failures.append(f"{filename}: 超过 {MAX_FILE_SIZE_MB}MB 限制")
            continue

        try:
            text, _metadata = DocumentParserFactory.parse(filename, content_bytes)
            if not text or not text.strip():
                raise ValueError("解析后内容为空")
            chunks = _get_splitter().split(text=text, file_name=filename, file_type=ext, category=kb_name)
        except Exception as exc:
            fail_count += 1
            failures.append(f"{filename}: {str(exc)[:80]}")
            logger.error(f"Parse/split failed for {filename}: {exc}", exc_info=True)
            continue

        inserted = 0
        failed_chunks = 0
        for chunk in chunks:
            chunk_text = chunk.get("text", "")
            if not chunk_text or not chunk_text.strip():
                continue
            try:
                vector = embedding.embed_query(chunk_text)
                insert_document(
                    content=chunk_text,
                    vector=vector,
                    filename=filename,
                    page_number=chunk.get("metadata", {}).get("page_number"),
                    category=kb_name,
                    metadata=chunk.get("metadata", {}),
                    kb_name=kb_name,
                )
                inserted += 1
            except Exception as exc:
                failed_chunks += 1
                logger.error(f"Chunk insert failed in {filename}: {exc}")

        if inserted > 0:
            success_count += 1
            if failed_chunks:
                failures.append(f"{filename}: 部分分片失败 ({failed_chunks}/{len(chunks)})")
        else:
            fail_count += 1
            failures.append(f"{filename}: 所有分片入库失败")

    return {"total": len(files), "success": success_count, "failed": fail_count, "failures": failures[:20]}


@router.post("/retrieve", response_model=RetrieveResponse)
def retrieve(req: RetrieveRequest):
    """检索调试接口：直接跑混合检索管道，不经过 LLM。"""
    try:
        pipeline = RetrievalPipeline(top_k=req.top_k)
        hits = pipeline.retrieve(req.query, req.kb_name)
    except Exception as exc:
        logger.error(f"Retrieval failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"检索失败：{exc}")
    return RetrieveResponse(
        hits=[
            {
                "score": hit.get("score", 0.0),
                "content": hit.get("content", ""),
                "metadata": hit.get("metadata") or {},
            }
            for hit in hits
        ]
    )
