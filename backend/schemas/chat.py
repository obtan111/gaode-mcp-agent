"""聊天接口的请求/响应模型。"""

from typing import List, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    # 关闭 pydantic 的 "model_" 前缀保留区检查，避免 model_type 字段触发启动警告
    model_config = {"protected_namespaces": ()}

    message: str = Field(..., min_length=1, max_length=8000, description="用户消息")
    session_id: Optional[str] = Field(None, description="会话 ID，为空则自动创建新会话")
    model_type: str = Field("deepseek", description="deepseek / deepseek-vl / zhipu / zhipu-4v")
    images: List[str] = Field(default_factory=list, description="base64 data URI 图片列表")
    tts: bool = Field(False, description="是否在回复中附带 TTS 音频（data URI）")


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    elapsed_ms: int
    audio: Optional[str] = Field(None, description="TTS 音频的 base64 data URI（请求 tts=true 时返回）")
