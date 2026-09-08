"""全局 token 流总线。

answer_generation 节点内流式生成时，把增量文本实时转发给上层通道
（WebSocket/SSE）。当前后端是"单连接同刻单轮"模型，因此用模块级
全局变量即可，无需 contextvar 跨线程传播。

API：
- set_token_sink(fn)  注册转发回调（由上层通道设置，None 表示摘除）
- emit_token(text)    节点内调用，把增量文本交给 sink
- emitted_chars()     本轮已转发的字符数（用于判断是否真流式生效）
- reset()             每轮开始时清零计数
"""

from typing import Callable, Optional

_sink: Optional[Callable[[str], None]] = None
_emitted: int = 0


def set_token_sink(sink: Optional[Callable[[str], None]]) -> None:
    global _sink
    _sink = sink


def emit_token(text: str) -> None:
    global _emitted
    if not text:
        return
    _emitted += len(text)
    if _sink is not None:
        try:
            _sink(text)
        except Exception:
            # 转发失败不影响节点主流程
            pass


def emitted_chars() -> int:
    return _emitted


def reset() -> None:
    global _emitted
    _emitted = 0
