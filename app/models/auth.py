from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class GitHubIdentityData(BaseModel):
    provider: Literal["github"] = "github"
    github_id: int = Field(ge=0)
    login: str
    name: str | None = None
    email: str | None = None
    avatar_url: str | None = None
    html_url: str | None = None
    token_type: str
    scope: list[str] = Field(default_factory=list)
    processed_at: str


class GitHubIdentityResponse(BaseModel):
    status: Literal["success"] = "success"
    data: GitHubIdentityData