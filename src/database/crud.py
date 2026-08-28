import json
import math
import hashlib
from typing import Any, Dict, List, Optional
from uuid import UUID

import numpy as np

from src.database.supabase_client import get_supabase_client
from src.database.pgvector_state import is_pgvector_available, set_pgvector_available
from src.utils.logger import setup_logger
from src.utils.retry import retry

logger = setup_logger("crud")

# 缓存数据库列存在性检查结果，避免反复查询
_content_hash_column_exists: Optional[bool] = None


def _check_content_hash_column() -> bool:
    """
    检查 content_hash 列是否存在于 documents 表中。
    
    结果会被缓存，避免每次都查询数据库。
    如果列不存在，返回 False，后续的重复检查会被跳过。
    """
    global _content_hash_column_exists
    if _content_hash_column_exists is not None:
        return _content_hash_column_exists
    
    try:
        client = get_supabase_client()
        
        def check_func(sb_client):
            result = sb_client.table("documents").select("id, content_hash").limit(1).execute()
            return result.data
        
        client.execute_with_client(check_func)
        _content_hash_column_exists = True
        logger.info("content_hash column exists in documents table")
    except Exception as e:
        error_msg = str(e).lower()
        if 'content_hash does not exist' in error_msg or 'column' in error_msg:
            _content_hash_column_exists = False
            logger.warning("content_hash column NOT found in documents table - duplicate checking disabled")
        else:
            # 其他错误不缓存，下次重试
            logger.warning(f"Failed to check content_hash column: {e}")
            _content_hash_column_exists = False
    
    return _content_hash_column_exists


def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
    try:
        v1_np = np.array(v1, dtype=np.float32)
        v2_np = np.array(v2, dtype=np.float32)
        norm1 = np.linalg.norm(v1_np)
        norm2 = np.linalg.norm(v2_np)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(v1_np, v2_np) / (norm1 * norm2))
    except Exception:
        dot_product = sum(a * b for a, b in zip(v1, v2))
        mag1 = math.sqrt(sum(a * a for a in v1))
        mag2 = math.sqrt(sum(b * b for b in v2))
        if mag1 == 0 or mag2 == 0:
            return 0.0
        return dot_product / (mag1 * mag2)


def _serialize_jsonb(data: Any) -> Any:
    if data is None:
        return None
    return json.loads(json.dumps(data))


def _compute_content_hash(content: str) -> str:
    """
    计算文档内容的MD5哈希值，用于去重。
    
    参数：
    - content: 文档内容
    
    返回：
    - 32位MD5哈希字符串
    """
    return hashlib.md5(content.encode("utf-8")).hexdigest()


@retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0, timeout=30.0)
def check_duplicate_document(content: str, kb_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    检查是否存在重复文档。
    
    通过内容hash检查同一知识库中是否已存在相同内容的文档。
    如果 content_hash 列不存在，则跳过重复检查。
    
    参数：
    - content: 文档内容
    - kb_name: 知识库名称
    
    返回：
    - None: 不存在重复（或列不存在，跳过检查）
    - Dict: 已存在的重复文档信息
    """
    # 如果 content_hash 列不存在，跳过重复检查
    if not _check_content_hash_column():
        logger.debug("content_hash column not available, skipping duplicate check")
        return None
    
    client = get_supabase_client()
    content_hash = _compute_content_hash(content)
    
    def check_func(sb_client):
        query = sb_client.table("documents").select("id, content_hash").eq("content_hash", content_hash)
        if kb_name:
            query = query.eq("kb_name", kb_name)
        result = query.execute()
        return result.data
    
    try:
        results = client.execute_with_client(check_func)
        if results:
            logger.info(f"Found duplicate document with hash: {content_hash}")
            return results[0]
        return None
    except Exception as e:
        error_msg = str(e).lower()
        if 'content_hash does not exist' in error_msg or 'column' in error_msg:
            # 列不存在，更新缓存，跳过重复检查
            global _content_hash_column_exists
            _content_hash_column_exists = False
            logger.warning("content_hash column not found, disabling duplicate check")
            return None
        logger.error(f"Failed to check duplicate document: {str(e)}")
        return None


@retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0, timeout=30.0)
def insert_document(
    content: str,
    vector: List[float],
    filename: Optional[str] = None,
    page_number: Optional[int] = None,
    category: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    kb_name: Optional[str] = None,
    skip_duplicate: bool = True,
) -> Dict[str, Any]:
    """
    插入文档（具备幂等性）。
    
    参数：
    - content: 文档内容
    - vector: 向量表示
    - filename: 文件名
    - page_number: 页码
    - category: 分类
    - metadata: 元数据
    - kb_name: 知识库名称
    - skip_duplicate: 是否跳过重复文档（默认True）
    
    返回：
    - 插入的文档信息或已存在的重复文档信息
    """
    client = get_supabase_client()
    logger.info(f"Inserting document for file: {filename}, page: {page_number}")

    # 检查重复（如果 content_hash 列不存在，会自动跳过）
    if skip_duplicate:
        duplicate = check_duplicate_document(content, kb_name)
        if duplicate:
            logger.info(f"Skipping duplicate document: {duplicate['id']}")
            return duplicate

    doc_metadata = metadata.copy() if metadata else {}
    doc_metadata["embedding_vector"] = vector
    content_hash = _compute_content_hash(content)
    has_hash_column = _check_content_hash_column()

    def insert_func(sb_client):
        target_dim = 1024
        if vector and len(vector) < target_dim:
            padded_vector = vector + [0.0] * (target_dim - len(vector))
        elif vector and len(vector) > target_dim:
            padded_vector = vector[:target_dim]
        else:
            padded_vector = vector or [0.0] * target_dim
        
        data = {
            "content": content,
            "vector": padded_vector,
            "filename": filename,
            "page_number": page_number,
            "category": category,
            "metadata": _serialize_jsonb(doc_metadata),
            "kb_name": kb_name,
        }
        # 只有当 content_hash 列存在时才添加
        if has_hash_column:
            data["content_hash"] = content_hash
        
        result = sb_client.table("documents").insert(data).execute()
        return result.data[0] if result.data else None

    try:
        result = client.execute_with_client(insert_func)
        logger.info(f"Document inserted successfully: {result.get('id') if result else None}")
        return result
    except Exception as e:
        error_msg = str(e).lower()
        if 'content_hash' in error_msg and ('does not exist' in error_msg or 'column' in error_msg):
            # 如果因为 content_hash 列不存在而失败，更新缓存并重试（不带 content_hash）
            global _content_hash_column_exists
            _content_hash_column_exists = False
            logger.warning("content_hash column not found, retrying without it...")
            # 重试（不带 content_hash）
            data = {
                "content": content,
                "vector": vector,
                "filename": filename,
                "page_number": page_number,
                "category": category,
                "metadata": _serialize_jsonb(doc_metadata),
                "kb_name": kb_name,
            }
            def retry_func(sb_client):
                result = sb_client.table("documents").insert(data).execute()
                return result.data[0] if result.data else None
            try:
                result = client.execute_with_client(retry_func)
                logger.info(f"Document inserted successfully (retry): {result.get('id') if result else None}")
                return result
            except Exception as retry_error:
                logger.error(f"Failed to insert document even without content_hash: {retry_error}")
                raise
        logger.error(f"Failed to insert document: {str(e)}")
        raise


@retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0, timeout=30.0)
def search_documents_by_vector(
    query_vector: List[float],
    limit: int = 10,
    similarity_threshold: float = 0.3,
    kb_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    client = get_supabase_client()
    logger.info(f"Searching documents by vector, limit: {limit}, kb_name: {kb_name}")

    def search_func(sb_client):
        query = sb_client.table("documents").select("*")
        if kb_name:
            query = query.eq("kb_name", kb_name)
        result = query.execute()
        return result.data

    try:
        all_docs = client.execute_with_client(search_func)
        logger.info(f"Loaded {len(all_docs)} documents for vector search")

        scored_docs = []
        for doc in all_docs:
            metadata = doc.get("metadata", {})
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except:
                    metadata = {}
            
            embeddings = metadata.get("embedding_vector") or doc.get("embeddings") or doc.get("vector")
            if isinstance(embeddings, str):
                # pgvector 列经 PostgREST 返回为字符串 "[0.1,0.2,...]"，需先解析
                try:
                    embeddings = json.loads(embeddings)
                except (ValueError, TypeError):
                    embeddings = None
            if embeddings and isinstance(embeddings, list):
                similarity = _cosine_similarity(query_vector, embeddings)
                if similarity >= similarity_threshold:
                    scored_docs.append({"document": doc, "similarity": similarity})

        scored_docs.sort(key=lambda x: x["similarity"], reverse=True)
        results = []
        for item in scored_docs[:limit]:
            doc = item["document"].copy()
            doc["similarity"] = item["similarity"]
            results.append(doc)
        logger.info(f"Found {len(results)} matching documents")
        return results
    except Exception as e:
        logger.error(f"Failed to search documents by vector: {str(e)}")
        raise


@retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0, timeout=30.0)
def search_documents_by_keyword(
    keyword: str,
    limit: int = 10,
    kb_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    client = get_supabase_client()
    logger.info(f"Searching documents by keyword: {keyword}, limit: {limit}, kb_name: {kb_name}")

    def search_func(sb_client):
        query = sb_client.table("documents").select("*").limit(limit)

        if kb_name:
            query = query.eq("kb_name", kb_name)

        result = query.ilike("content", f"%{keyword}%").execute()
        return result.data

    try:
        results = client.execute_with_client(search_func)
        logger.info(f"Found {len(results)} documents matching keyword")
        return results
    except Exception as e:
        logger.error(f"Failed to search documents by keyword: {str(e)}")
        raise


@retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0, timeout=30.0)
def delete_document_by_id(document_id: UUID) -> bool:
    client = get_supabase_client()
    logger.info(f"Deleting document by id: {document_id}")

    def delete_func(sb_client):
        result = sb_client.table("documents").delete().eq("id", str(document_id)).execute()
        return len(result.data) > 0

    try:
        success = client.execute_with_client(delete_func)
        logger.info(f"Document deletion {'successful' if success else 'failed'}")
        return success
    except Exception as e:
        logger.error(f"Failed to delete document by id: {str(e)}")
        raise


@retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0, timeout=30.0)
def delete_documents_by_filename(filename: str) -> int:
    client = get_supabase_client()
    logger.info(f"Deleting documents by filename: {filename}")

    def delete_func(sb_client):
        result = sb_client.table("documents").delete().eq("filename", filename).execute()
        return len(result.data)

    try:
        count = client.execute_with_client(delete_func)
        logger.info(f"Deleted {count} documents for filename: {filename}")
        return count
    except Exception as e:
        logger.error(f"Failed to delete documents by filename: {str(e)}")
        raise


@retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0, timeout=30.0)
def get_documents_by_kb(kb_name: Optional[str]) -> List[Dict[str, Any]]:
    client = get_supabase_client()
    logger.info(f"Getting documents by kb_name: {kb_name}")

    def get_func(sb_client):
        query = sb_client.table("documents").select("*")
        if kb_name and kb_name.strip():
            query = query.eq("kb_name", kb_name)
        result = query.execute()
        return result.data

    try:
        results = client.execute_with_client(get_func)
        logger.info(f"Found {len(results)} documents for kb: {kb_name}")
        return results
    except Exception as e:
        logger.error(f"Failed to get documents by kb: {str(e)}")
        raise


@retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0, timeout=30.0)
def get_knowledge_base_names() -> List[str]:
    """
    获取所有知识库名称列表（高效查询）。
    
    通过直接查询 distinct kb_name，避免全表扫描和客户端去重。
    
    返回：
    - 知识库名称列表
    """
    client = get_supabase_client()
    logger.info("Getting distinct knowledge base names")

    def get_func(sb_client):
        result = sb_client.table("documents").select("kb_name", count="exact").execute()
        return result.data

    try:
        results = client.execute_with_client(get_func)
        kb_names = sorted(set(doc.get("kb_name", "") for doc in results if doc.get("kb_name")))
        logger.info(f"Found {len(kb_names)} knowledge bases")
        return kb_names
    except Exception as e:
        logger.error(f"Failed to get knowledge base names: {str(e)}")
        return []


@retry(max_retries=2, backoff_factor=1.0, initial_delay=0.3, timeout=10.0)
def create_session(
    title: str,
    summary: Optional[str] = None,
    messages: Optional[List[Dict[str, Any]]] = None,
    session_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    client = get_supabase_client()
    logger.info(f"Creating chat session: {title}, session_id={session_id}")

    def create_func(sb_client):
        data = {
            "title": title,
            "summary": summary,
            "messages": _serialize_jsonb(messages or []),
        }
        if session_id:
            data["id"] = str(session_id)
        result = sb_client.table("chat_session").insert(data).execute()
        return result.data[0] if result.data else None

    try:
        result = client.execute_with_client(create_func)
        logger.info(f"Chat session created successfully: {result.get('id') if result else None}")
        return result
    except Exception as e:
        logger.error(f"Failed to create chat session: {str(e)}")
        raise


@retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0, timeout=30.0)
def get_session_by_id(session_id: UUID) -> Optional[Dict[str, Any]]:
    client = get_supabase_client()
    logger.info(f"Getting chat session by id: {session_id}")

    def get_func(sb_client):
        result = sb_client.table("chat_session").select("*").eq("id", str(session_id)).execute()
        return result.data[0] if result.data else None

    try:
        result = client.execute_with_client(get_func)
        logger.info(f"Chat session {'found' if result else 'not found'}")
        return result
    except Exception as e:
        logger.error(f"Failed to get chat session by id: {str(e)}")
        raise


@retry(max_retries=2, backoff_factor=1.0, initial_delay=0.3, timeout=10.0)
def update_session(
    session_id: UUID,
    title: Optional[str] = None,
    summary: Optional[str] = None,
    append_message: Optional[Dict[str, Any]] = None,
    append_messages: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    client = get_supabase_client()
    logger.info(f"Updating chat session: {session_id}")

    def update_func(sb_client):
        # 如果需要追加消息，先查询现有消息
        messages_to_append = []
        if append_message:
            messages_to_append.append(append_message)
        if append_messages:
            messages_to_append.extend(append_messages)
        
        updates = {}
        if title is not None:
            updates["title"] = title
        if summary is not None:
            updates["summary"] = summary
        updates["updated_at"] = "now()"
        
        # 如果有消息要追加，先获取现有消息
        if messages_to_append:
            result = sb_client.table("chat_session").select("messages").eq("id", str(session_id)).execute()
            if not result.data or len(result.data) == 0:
                raise ValueError(f"Session not found: {session_id}")
            session = result.data[0]
            existing_messages = session.get("messages", [])
            if isinstance(existing_messages, str):
                existing_messages = json.loads(existing_messages)
            for msg in messages_to_append:
                existing_messages.append(msg)
            updates["messages"] = _serialize_jsonb(existing_messages)
        
        # 执行更新
        result = sb_client.table("chat_session").update(updates).eq("id", str(session_id)).execute()
        return result.data[0] if result.data else None

    try:
        result = client.execute_with_client(update_func)
        logger.info(f"Chat session updated successfully: {session_id}")
        return result
    except Exception as e:
        logger.error(f"Failed to update chat session: {str(e)}")
        raise


@retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0, timeout=30.0)
def delete_session(session_id: UUID) -> bool:
    client = get_supabase_client()
    logger.info(f"Deleting chat session: {session_id}")

    def delete_func(sb_client):
        result = sb_client.table("chat_session").delete().eq("id", str(session_id)).execute()
        return len(result.data) > 0

    try:
        success = client.execute_with_client(delete_func)
        logger.info(f"Chat session deletion {'successful' if success else 'failed'}")
        return success
    except Exception as e:
        logger.error(f"Failed to delete chat session: {str(e)}")
        raise


@retry(max_retries=1, backoff_factor=0.5, initial_delay=0.2, timeout=5.0)
def list_sessions(page: int = 1, page_size: int = 10) -> List[Dict[str, Any]]:
    client = get_supabase_client()
    logger.info(f"Listing chat sessions, page: {page}, page_size: {page_size}")

    def list_func(sb_client):
        offset = (page - 1) * page_size
        result = sb_client.table("chat_session").select("*").order("created_at", desc=True).range(offset, offset + page_size - 1).execute()
        return result.data

    try:
        results = client.execute_with_client(list_func)
        logger.info(f"Found {len(results)} chat sessions")
        return results
    except Exception as e:
        logger.error(f"Failed to list chat sessions: {str(e)}")
        raise


@retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0, timeout=30.0)
def log_mcp_call(
    tool_name: str,
    parameters: Optional[Dict[str, Any]] = None,
    result: Optional[Dict[str, Any]] = None,
    token_usage: Optional[int] = None,
    session_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    client = get_supabase_client()
    logger.info(f"Logging MCP call: {tool_name}, session_id: {session_id}")

    def log_func(sb_client):
        data = {
            "tool_name": tool_name,
            "parameters": _serialize_jsonb(parameters),
            "result": _serialize_jsonb(result),
            "token_usage": token_usage,
            "session_id": str(session_id) if session_id else None,
        }
        result_data = sb_client.table("mcp_call_log").insert(data).execute()
        return result_data.data[0] if result_data.data else None

    try:
        result_data = client.execute_with_client(log_func)
        logger.info(f"MCP call logged successfully: {result_data.get('id') if result_data else None}")
        return result_data
    except Exception as e:
        logger.error(f"Failed to log MCP call: {str(e)}")
        raise


@retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0, timeout=30.0)
def get_logs_by_session(session_id: UUID, limit: int = 50) -> List[Dict[str, Any]]:
    client = get_supabase_client()
    logger.info(f"Getting MCP logs by session: {session_id}, limit: {limit}")

    def get_func(sb_client):
        result = sb_client.table("mcp_call_log").select("*").eq("session_id", str(session_id)).order("call_time", desc=True).limit(limit).execute()
        return result.data

    try:
        results = client.execute_with_client(get_func)
        logger.info(f"Found {len(results)} MCP logs for session: {session_id}")
        return results
    except Exception as e:
        logger.error(f"Failed to get MCP logs by session: {str(e)}")
        raise


@retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0, timeout=30.0)
def get_logs_by_tool(tool_name: str, limit: int = 50) -> List[Dict[str, Any]]:
    client = get_supabase_client()
    logger.info(f"Getting MCP logs by tool: {tool_name}, limit: {limit}")

    def get_func(sb_client):
        result = sb_client.table("mcp_call_log").select("*").eq("tool_name", tool_name).order("call_time", desc=True).limit(limit).execute()
        return result.data

    try:
        results = client.execute_with_client(get_func)
        logger.info(f"Found {len(results)} MCP logs for tool: {tool_name}")
        return results
    except Exception as e:
        logger.error(f"Failed to get MCP logs by tool: {str(e)}")
        raise


@retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0, timeout=30.0)
def create_travel_plan(
    title: str,
    destination: str,
    days: int,
    budget: Optional[float] = None,
    plan_data: Optional[Dict[str, Any]] = None,
    weather_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    client = get_supabase_client()
    logger.info(f"Creating travel plan: {title}, destination: {destination}")

    def create_func(sb_client):
        data = {
            "title": title,
            "destination": destination,
            "days": days,
            "budget": budget,
            "plan_data": _serialize_jsonb(plan_data or {}),
            "weather_info": _serialize_jsonb(weather_info),
        }
        result = sb_client.table("travel_plan").insert(data).execute()
        return result.data[0] if result.data else None

    try:
        result = client.execute_with_client(create_func)
        logger.info(f"Travel plan created successfully: {result.get('id') if result else None}")
        return result
    except Exception as e:
        logger.error(f"Failed to create travel plan: {str(e)}")
        raise


@retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0, timeout=30.0)
def get_travel_plan_by_id(plan_id: UUID) -> Optional[Dict[str, Any]]:
    client = get_supabase_client()
    logger.info(f"Getting travel plan by id: {plan_id}")

    def get_func(sb_client):
        result = sb_client.table("travel_plan").select("*").eq("id", str(plan_id)).execute()
        return result.data[0] if result.data else None

    try:
        result = client.execute_with_client(get_func)
        logger.info(f"Travel plan {'found' if result else 'not found'}")
        return result
    except Exception as e:
        logger.error(f"Failed to get travel plan by id: {str(e)}")
        raise


@retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0, timeout=30.0)
def update_travel_plan(
    plan_id: UUID,
    title: Optional[str] = None,
    destination: Optional[str] = None,
    days: Optional[int] = None,
    budget: Optional[float] = None,
    plan_data: Optional[Dict[str, Any]] = None,
    weather_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    client = get_supabase_client()
    logger.info(f"Updating travel plan: {plan_id}")

    def update_func(sb_client):
        updates = {}
        if title is not None:
            updates["title"] = title
        if destination is not None:
            updates["destination"] = destination
        if days is not None:
            updates["days"] = days
        if budget is not None:
            updates["budget"] = budget
        if plan_data is not None:
            updates["plan_data"] = _serialize_jsonb(plan_data)
        if weather_info is not None:
            updates["weather_info"] = _serialize_jsonb(weather_info)

        if not updates:
            raise ValueError("No updates provided")

        result = sb_client.table("travel_plan").update(updates).eq("id", str(plan_id)).execute()
        return result.data[0] if result.data else None

    try:
        result = client.execute_with_client(update_func)
        logger.info(f"Travel plan updated successfully: {plan_id}")
        return result
    except Exception as e:
        logger.error(f"Failed to update travel plan: {str(e)}")
        raise


@retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0, timeout=30.0)
def delete_travel_plan(plan_id: UUID) -> bool:
    client = get_supabase_client()
    logger.info(f"Deleting travel plan: {plan_id}")

    def delete_func(sb_client):
        result = sb_client.table("travel_plan").delete().eq("id", str(plan_id)).execute()
        return len(result.data) > 0

    try:
        success = client.execute_with_client(delete_func)
        logger.info(f"Travel plan deletion {'successful' if success else 'failed'}")
        return success
    except Exception as e:
        logger.error(f"Failed to delete travel plan: {str(e)}")
        raise


@retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0, timeout=30.0)
def list_travel_plans(
    destination: Optional[str] = None,
    page: int = 1,
    page_size: int = 10,
) -> List[Dict[str, Any]]:
    client = get_supabase_client()
    logger.info(f"Listing travel plans, destination: {destination}, page: {page}, page_size: {page_size}")

    def list_func(sb_client):
        offset = (page - 1) * page_size
        query = sb_client.table("travel_plan").select("*").order("created_at", desc=True).range(offset, offset + page_size - 1)

        if destination:
            query = query.eq("destination", destination)

        result = query.execute()
        return result.data

    try:
        results = client.execute_with_client(list_func)
        logger.info(f"Found {len(results)} travel plans")
        return results
    except Exception as e:
        logger.error(f"Failed to list travel plans: {str(e)}")
        raise