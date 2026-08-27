"""后端共享组件的懒加载单例管理。

import 阶段绝不创建任何模型、连接或网络资源；首次通过 get_* 调用时才初始化。
这样 `python -m uvicorn backend.main:app` 的导入开销极小，测试和 Docker 构建
也不会在 import 时就要求所有 API Key 必须可用。
"""

import threading
from typing import Any, Callable, Dict

_instances: Dict[str, Any] = {}
_factories: Dict[str, Callable[[], Any]] = {}
_lock = threading.Lock()


def _register(name: str, factory: Callable[[], Any]) -> Callable[[], Any]:
    """注册懒加载工厂，返回线程安全的单例 getter（双重检查锁）。"""
    _factories[name] = factory

    def getter() -> Any:
        if name not in _instances:
            with _lock:
                if name not in _instances:
                    _instances[name] = factory()
        return _instances[name]

    return getter


def get_agent_graph():
    from src.agent.graph import AgentGraph

    return _register("agent_graph", AgentGraph)()


def get_speech_recognizer():
    from src.llm.speech import SpeechRecognition

    return _register("speech_recognizer", SpeechRecognition)()


def get_text_to_speech():
    from src.llm.speech import TextToSpeech

    return _register(
        "text_to_speech",
        lambda: TextToSpeech(engine="zhipu"),
    )()


def get_embedding_factory():
    from src.llm.embedding import EmbeddingFactory

    return _register("embedding_factory", EmbeddingFactory)()
