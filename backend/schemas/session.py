"""会话管理接口的请求模型。"""

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    title: str = Field("新对话", max_length=100)


class SessionUpdate(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
