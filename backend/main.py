"""FastAPI 后端入口：把 src/ 下已有的智能体与 RAG 能力包装成 Web 服务。

启动（在项目根目录执行）：
    python -m uvicorn backend.main:app --reload --port 8100

接口文档：
    http://127.0.0.1:8000/docs
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers import chat, kb, sessions, voice


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时预热核心组件；预热失败只告警，不让服务起不来（Key 未配齐也能先看文档页）。"""
    try:
        from backend.core.deps import get_agent_graph

        get_agent_graph().compile()
        logging.getLogger("backend").info("Agent graph warmed up")
    except Exception as exc:
        logging.getLogger("backend").warning(f"Warmup skipped: {exc}")
    yield


app = FastAPI(title="私人助手 API", version="0.1.0", lifespan=lifespan)

# CORS：默认放行 Vite 开发服务器；生产部署用 FRONTEND_ORIGINS 环境变量覆盖
_origins = os.getenv("FRONTEND_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(sessions.router)
app.include_router(kb.router)
app.include_router(voice.router)


@app.get("/api/health", tags=["system"])
def health():
    return {"status": "ok"}
