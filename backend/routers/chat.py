"""聊天路由：提供普通 JSON 与 SSE 流式两种消费方式。"""

import json
from typing import Generator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.schemas.chat import ChatRequest, ChatResponse
from backend.services.agent_runner import ensure_session, iter_chat_events, run_chat_sync

router = APIRouter(prefix="/api/chat", tags=["chat"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    # Nginx 反向代理默认会缓冲响应，必须显式关闭才能看到逐字效果
    "X-Accel-Buffering": "no",
}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """一次性返回完整回答。

    同步路由由 FastAPI 自动放入线程池执行，不会阻塞事件循环，
    适合作为前端的保底通道（SSE 不可用时降级）。
    """
    session_id = ensure_session(req.session_id)
    result = run_chat_sync(req.message, session_id, req.model_type, req.images, req.tts)
    return ChatResponse(**result)


@router.post("/stream")
def chat_stream(req: ChatRequest) -> StreamingResponse:
    """SSE 流式回答，事件定义见 services.agent_runner.iter_chat_events。"""
    session_id = ensure_session(req.session_id)

    def source() -> Generator[str, None, None]:
        for event, data in iter_chat_events(req.message, session_id, req.model_type, req.images, req.tts):
            yield _sse(event, data)

    return StreamingResponse(source(), media_type="text/event-stream", headers=_SSE_HEADERS)
