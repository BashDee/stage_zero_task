from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CreateProfileRequest(BaseModel):
    name: object | None = None


class ProfileData(BaseModel):
    id: str
    name: str
    gender: str
    gender_probability: float = Field(ge=0.0, le=1.0)
    age: int = Field(ge=0)
    age_group: Literal["child", "teenager", "adult", "senior"]
    country_id: str
    country_name: str
    country_probability: float = Field(ge=0.0, le=1.0)
    created_at: str


class ProfileSuccessResponse(BaseModel):
    status: Literal["success"] = "success"
    data: ProfileData


class ProfileAlreadyExistsResponse(BaseModel):
    status: Literal["success"] = "success"
    message: Literal["Profile already exists"] = "Profile already exists"
    data: ProfileData


class PaginationLinks(BaseModel):
    self: str
    next: str | None = None
    prev: str | None = None


class ProfilesListResponse(BaseModel):
    status: Literal["success"] = "success"
    page: int = Field(ge=1)
    limit: int = Field(ge=1, le=50)
    total: int = Field(ge=0)
    total_pages: int = Field(ge=0)
    links: PaginationLinks
    data: list[ProfileData]
