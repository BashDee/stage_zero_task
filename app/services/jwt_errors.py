from __future__ import annotations


class JWTError(Exception):
    """Base exception for JWT-related errors."""
    status_code = 400

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class InvalidTokenError(JWTError):
    """Token signature invalid or malformed."""
    status_code = 401
    message = "Invalid token"


class ExpiredTokenError(JWTError):
    """Token has expired."""
    status_code = 401
    message = "Token expired"


class RevokedTokenError(JWTError):
    """Token has been revoked (refresh token already used)."""
    status_code = 401
    message = "Token revoked or already used"


class MissingTokenError(JWTError):
    """No token provided."""
    status_code = 400
    message = "Missing token"
