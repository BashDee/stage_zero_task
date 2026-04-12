from typing import Literal

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    status: Literal["error"] = "error"
    message: str


class ClassifyData(BaseModel):
    name: str
    gender: str | None
    probability: float = Field(ge=0.0, le=1.0)
    sample_size: int = Field(ge=0)
    is_confident: bool
    processed_at: str


class SuccessResponse(BaseModel):
    status: Literal["success"] = "success"
    data: ClassifyData
