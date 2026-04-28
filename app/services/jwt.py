from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Optional

import jwt

from app.models.token import TokenPayload
from app.services.jwt_errors import (
    ExpiredTokenError,
    InvalidTokenError,
)

# Configuration
DEFAULT_ACCESS_EXPIRY_SECONDS = int(os.getenv("DEFAULT_ACCESS_EXPIRY_SECONDS", 180))  # 3 minutes
DEFAULT_REFRESH_EXPIRY_SECONDS = int(os.getenv("DEFAULT_REFRESH_EXPIRY_SECONDS", 300))  # 5 minutes


class JWTService:
    """Handles JWT signing and verification with configurable expiry."""

    def __init__(
        self,
        secret_key: Optional[str] = None,
        algorithm: str = "HS256",
        access_expiry_seconds: int = DEFAULT_ACCESS_EXPIRY_SECONDS,
        refresh_expiry_seconds: int = DEFAULT_REFRESH_EXPIRY_SECONDS,
    ):
        self._secret_key = secret_key or os.getenv("JWT_SECRET_KEY")
        if not self._secret_key:
            raise RuntimeError("JWT_SECRET_KEY is required and not set")
        self._algorithm = algorithm
        self._access_expiry_seconds = access_expiry_seconds
        self._refresh_expiry_seconds = refresh_expiry_seconds

    @staticmethod
    def _utc_now_timestamp() -> int:
        """Get current time as Unix timestamp."""
        return int(datetime.now(timezone.utc).timestamp())

    @staticmethod
    def _generate_jti() -> str:
        """Generate a unique JWT ID using secrets."""
        import secrets

        return secrets.token_urlsafe(32)

    def generate_access_token(self, github_id: int, login: str) -> str:
        """
        Generate a short-lived access token.

        Args:
            github_id: GitHub user ID
            login: GitHub login name

        Returns:
            Signed JWT token string
        """
        now = self._utc_now_timestamp()
        jti = self._generate_jti()
        payload_dict = {
            "sub": str(github_id),  # PyJWT requires sub to be string
            "login": login,
            "jti": jti,
            "token_type": "access",
            "exp": now + self._access_expiry_seconds,
        }
        return jwt.encode(payload_dict, self._secret_key, algorithm=self._algorithm)

    def generate_refresh_token(self, github_id: int, login: str) -> tuple[str, str]:
        """
        Generate a single-use refresh token with JTI.

        Args:
            github_id: GitHub user ID
            login: GitHub login name

        Returns:
            Tuple of (token, jti) where jti is the token ID for revocation tracking
        """
        now = self._utc_now_timestamp()
        jti = self._generate_jti()
        payload_dict = {
            "sub": str(github_id),  # PyJWT requires sub to be string
            "login": login,
            "jti": jti,
            "token_type": "refresh",
            "exp": now + self._refresh_expiry_seconds,
        }
        token = jwt.encode(payload_dict, self._secret_key, algorithm=self._algorithm)
        return token, jti

    def verify_access_token(self, token: str) -> TokenPayload:
        """
        Verify access token signature and expiry (stateless).

        Does NOT check revocation—access tokens are short-lived and
        not tracked in the database.

        Args:
            token: JWT token string

        Raises:
            InvalidTokenError: Token signature invalid or malformed
            ExpiredTokenError: Token has expired

        Returns:
            Decoded token payload
        """
        try:
            payload = jwt.decode(token, self._secret_key, algorithms=[self._algorithm])
            return TokenPayload(**payload)
        except jwt.ExpiredSignatureError as exc:
            raise ExpiredTokenError("Token expired") from exc
        except (jwt.InvalidTokenError, jwt.DecodeError) as exc:
            raise InvalidTokenError("Invalid token") from exc

    def verify_refresh_token(self, token: str) -> TokenPayload:
        """
        Verify refresh token signature, expiry, and extract JTI for revocation check.

        Does NOT check revocation status—that is done by the caller using the JTI.

        Args:
            token: JWT token string

        Raises:
            InvalidTokenError: Token signature invalid or malformed
            ExpiredTokenError: Token has expired

        Returns:
            Decoded token payload (includes jti for DB lookup)
        """
        try:
            payload = jwt.decode(token, self._secret_key, algorithms=[self._algorithm])
            return TokenPayload(**payload)
        except jwt.ExpiredSignatureError as exc:
            raise ExpiredTokenError("Token expired") from exc
        except (jwt.InvalidTokenError, jwt.DecodeError) as exc:
            raise InvalidTokenError("Invalid token") from exc

    def get_token_expiry_timestamp(self, github_id: int, token_type: str) -> int:
        """
        Get the expiry timestamp (Unix time) for a given token type.

        Used by repository to store token expiry in the database.
        """
        now = self._utc_now_timestamp()
        if token_type == "access":
            return now + self._access_expiry_seconds
        elif token_type == "refresh":
            return now + self._refresh_expiry_seconds
        else:
            raise ValueError(f"Unknown token_type: {token_type}")
