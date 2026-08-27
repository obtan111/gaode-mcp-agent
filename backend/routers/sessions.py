"""会话管理路由：对数据库 CRUD 层的薄封装。"""

import uuid

from fastapi import APIRouter, HTTPException, Query

from backend.schemas.session import SessionCreate, SessionUpdate
from src.database.crud import (
    create_session,
    delete_session,
    get_session_by_id,
    list_sessions,
    update_session,
)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _to_uuid(sid: str) -> uuid.UUID:
    try:
        return uuid.UUID(sid)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的会话 ID")


@router.get("")
def read_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    include_messages: bool = Query(False, description="列表页通常不需要消息体，按需开启"),
):
    items = list_sessions(page=page, page_size=page_size)
    if not include_messages:
        for item in items:
            item.pop("messages", None)
    return items


@router.post("", status_code=201)
def create(payload: SessionCreate):
    return create_session(title=payload.title, messages=[])


@router.get("/{session_id}")
def read_one(session_id: str):
    session = get_session_by_id(_to_uuid(session_id))
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


@router.patch("/{session_id}")
def rename(session_id: str, payload: SessionUpdate):
    updated = update_session(_to_uuid(session_id), title=payload.title)
    if not updated:
        raise HTTPException(status_code=404, detail="会话不存在")
    return updated


@router.delete("/{session_id}")
def remove(session_id: str):
    deleted = delete_session(_to_uuid(session_id))
    return {"ok": bool(deleted)}
