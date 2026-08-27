"""知识库路由：文档上传并向量化、内容查看、删除与检索调试。"""

import os
from typing import List

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.schemas.kb import RetrieveRequest, RetrieveResponse
from src.config.settings import Config
from src.database.crud import (
    delete_documents_by_filename,
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


@router.get("/{kb_name}/documents")
def read_documents(kb_name: str):
    """返回知识库全部分片（剥离 vector 大字段）。"""
    docs = get_documents_by_kb(kb_name)
    return [{k: v for k, v in doc.items() if k != "vector"} for doc in docs]


@router.delete("/{kb_name}")
def remove_kb(kb_name: str):
    docs = get_documents_by_kb(kb_name)
    filenames = {doc.get("filename", "") for doc in docs} - {""}
    deleted_chunks = sum(delete_documents_by_filename(name) or 0 for name in filenames)
    logger.info(f"Deleted KB '{kb_name}': {deleted_chunks} chunks")
    return {"ok": True, "deleted_chunks": deleted_chunks}


@router.post("/{kb_name}/documents")
async def upload_documents(kb_name: str, files: List[UploadFile] = File(...)):
    """上传文档并完成 解析 → 切分 → 向量化 → 入库 全流程。"""
    from backend.core.deps import get_embedding_factory

    embedding = get_embedding_factory().create_embedding("zhipu")
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
