"""知识库接口的请求/响应模型。"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class RetrieveRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    kb_name: Optional[str] = Field(None, description="为空则检索全部知识库")
    top_k: int = Field(5, ge=1, le=20)


class RetrieveHit(BaseModel):
    score: float
    content: str
    metadata: Dict = Field(default_factory=dict)


class RetrieveResponse(BaseModel):
    hits: List[RetrieveHit]
