from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.services.jwt_errors import ExpiredTokenError, InvalidTokenError

ERROR_INVALID_TOKEN = "Invalid token"
ERROR_MISSING_TOKEN = "Missing access token"
ERROR_INACTIVE_USER = "User account is inactive"


@dataclass(frozen=True)
class AuthenticatedUserContext:
    """Normalized request user context attached by authentication middleware."""

    id: str
    role: str
    is_active: bool


class AccessTokenVerifier(Protocol):
    """Contract for access-token verification."""

    def verify_access_token(self, token: str):
        ...


class UserLookupRepository(Protocol):
    """Contract for loading users by GitHub identity."""

    def find_by_github_id(self, github_id: int):
        ...


class AccessTokenAuthMiddleware(BaseHTTPMiddleware):
    """Protects /api/* routes by validating bearer access tokens."""

    def _error(self, status_code: int, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={"status": "error", "message": message},
        )

    @staticmethod
    def _extract_bearer_token(request: Request) -> str:
        authorization = request.headers.get("Authorization")
        if authorization is None or authorization.strip() == "":
            raise ValueError(ERROR_MISSING_TOKEN)

        parts = authorization.strip().split(" ", maxsplit=1)
        if len(parts) != 2 or parts[0].lower() != "bearer" or parts[1].strip() == "":
            raise InvalidTokenError(ERROR_INVALID_TOKEN)
        return parts[1].strip()

    @staticmethod
    def _is_protected_path(path: str) -> bool:
        return path == "/api" or path.startswith("/api/")

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self._is_protected_path(request.url.path):
            return await call_next(request)

        verifier: AccessTokenVerifier | None = getattr(request.app.state, "jwt_service", None)
        user_repo: UserLookupRepository | None = getattr(request.app.state, "user_repository", None)

        if verifier is None or user_repo is None:
            return self._error(500, "Authentication service not initialized")

        try:
            token = self._extract_bearer_token(request)
            payload = verifier.verify_access_token(token)
            if payload.token_type != "access":
                raise InvalidTokenError(ERROR_INVALID_TOKEN)

            github_id = int(payload.sub)
            user = user_repo.find_by_github_id(github_id)
            if user is None:
                return self._error(401, ERROR_INVALID_TOKEN)
            if not user.is_active:
                return self._error(403, ERROR_INACTIVE_USER)

            request.state.user = AuthenticatedUserContext(
                id=user.id,
                role=user.role,
                is_active=user.is_active,
            )
        except ValueError:
            return self._error(401, ERROR_MISSING_TOKEN)
        except ExpiredTokenError:
            return self._error(401, "Token expired")
        except InvalidTokenError:
            return self._error(401, ERROR_INVALID_TOKEN)
        except Exception:
            return self._error(401, ERROR_INVALID_TOKEN)

        return await call_next(request)
