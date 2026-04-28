from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TokenPayload(BaseModel):
    """JWT claims payload."""
    sub: str  # github_id as string (PyJWT requirement)
    login: str
    jti: str  # JWT ID for revocation tracking
    token_type: Literal["access", "refresh"]
    exp: int  # Unix timestamp


class RefreshTokenRequest(BaseModel):
    """Request body for POST /auth/refresh."""
    refresh_token: str = Field(..., description="Current refresh token")


class TokenData(BaseModel):
    """Token pair returned after successful authentication or refresh."""
    access_token: str = Field(..., description="Short-lived access token (3 min)")
    refresh_token: str = Field(..., description="Single-use refresh token (5 min)")
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(..., description="Access token expiry in seconds")


class TokenResponse(BaseModel):
    """Unified response for token endpoints."""
    status: Literal["success"] = "success"
    data: TokenData


class ErrorResponse(BaseModel):
    """Standard error response."""
    status: Literal["error"] = "error"
    message: str
