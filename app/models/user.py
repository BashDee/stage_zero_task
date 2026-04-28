from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CreateUserRequest(BaseModel):
    """Request body for explicit user creation (future use)."""
    github_id: int = Field(gt=0)
    username: str
    email: str | None = None
    avatar_url: str | None = None


class UserData(BaseModel):
    """User data for API responses."""
    id: str
    github_id: int
    username: str
    email: str | None = None
    avatar_url: str | None = None
    role: str
    is_active: bool
    last_login_at: str | None = None
    created_at: str


class UserSuccessResponse(BaseModel):
    """Standard user response wrapper."""
    status: Literal["success"] = "success"
    data: UserData
