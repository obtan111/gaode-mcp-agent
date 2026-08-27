"""FastAPI 后端的轻量冒烟测试。

只校验路由注册与模型定义，不触发任何网络请求或组件初始化，
即使没有配置 API Key 也能运行。
"""

import pytest

fastapi = pytest.importorskip("fastapi")


def test_app_importable():
    from backend.main import app

    assert app is not None


def test_core_routes_registered():
    """通过 OpenAPI 契约断言路由，不依赖 FastAPI 内部的 Route 对象结构。"""
    from backend.main import app

    spec = app.openapi()
    paths = set(spec.get("paths", {}))
    assert "/api/health" in paths
    assert "/api/chat" in paths
    assert "/api/chat/stream" in paths
    assert "/api/sessions" in paths
    assert "/api/kb" in paths
    assert "/api/kb/retrieve" in paths


def test_chat_request_validation():
    from pydantic import ValidationError

    from backend.schemas.chat import ChatRequest

    with pytest.raises(ValidationError):
        ChatRequest(message="")
    req = ChatRequest(message="你好")
    assert req.model_type == "deepseek"
    assert req.images == []
