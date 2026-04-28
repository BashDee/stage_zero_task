from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.models.auth import GitHubIdentityResponse
from app.models.classify import ErrorResponse
from app.models.token import RefreshTokenRequest, TokenResponse
from app.services.github_oauth import (
    GitHubOAuthError,
    GitHubOAuthService,
    InMemoryOAuthStateStore,
    get_github_oauth_config,
)
from app.services.jwt_errors import JWTError
from app.services.token_manager import TokenManager
from app.services.users import UserService
from app.services.user_errors import UserRepositoryError


router = APIRouter(prefix="/auth", tags=["authentication"])


def _build_error_response(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(message=message).model_dump(),
    )


def _get_state_store(request: Request) -> InMemoryOAuthStateStore:
    store = getattr(request.app.state, "github_oauth_state_store", None)
    if store is None:
        store = InMemoryOAuthStateStore()
        request.app.state.github_oauth_state_store = store
    return store


def _get_service(request: Request) -> GitHubOAuthService:
    config = get_github_oauth_config()
    return GitHubOAuthService(
        request.app.state.http_client,
        config,
        _get_state_store(request),
    )


def _get_token_manager(request: Request) -> TokenManager:
    manager = getattr(request.app.state, "token_manager", None)
    if manager is None:
        raise RuntimeError("TokenManager not initialized in app state")
    return manager


def _get_user_service(request: Request) -> UserService:
    service = getattr(request.app.state, "user_service", None)
    if service is None:
        raise RuntimeError("UserService not initialized in app state")
    return service


@router.get("/github")
async def github_login(request: Request):
    service = _get_service(request)
    callback_url = str(request.url_for("github_callback"))
    authorization = service.build_authorization_request(callback_url)
    return RedirectResponse(url=authorization.redirect_url, status_code=302)


@router.get(
    "/github/callback",
    name="github_callback",
    response_model=TokenResponse | ErrorResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid callback code or state"},
        502: {"model": ErrorResponse, "description": "GitHub upstream failure"},
    },
)
async def github_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    if error is not None:
        return _build_error_response(400, error_description or error)

    service = _get_service(request)
    token_manager = _get_token_manager(request)
    user_service = _get_user_service(request)
    callback_url = str(request.url_for("github_callback"))

    try:
        identity = await service.exchange_code(code=code, state=state, callback_url=callback_url)
    except GitHubOAuthError as exc:
        message = getattr(exc, "message", str(exc))
        status_code = getattr(exc, "status_code", 400)
        return _build_error_response(status_code, message)

    # Create or update user in database
    try:
        user_service.get_or_create(
            github_id=identity.github_id,
            username=identity.login,
            email=identity.email,
            avatar_url=identity.avatar_url,
        )
    except UserRepositoryError as exc:
        return _build_error_response(500, "Failed to persist user")

    # Issue local tokens after successful GitHub identity exchange and user persistence
    try:
        token_data = token_manager.issue_tokens(
            github_id=identity.github_id,
            login=identity.login,
        )
        payload = TokenResponse(data=token_data)
        return JSONResponse(status_code=200, content=payload.model_dump())
    except Exception as exc:
        return _build_error_response(500, "Failed to issue tokens")


@router.post(
    "/refresh",
    response_model=TokenResponse | ErrorResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Missing or invalid token"},
        401: {"model": ErrorResponse, "description": "Token expired or revoked"},
    },
)
async def refresh_token(
    request: Request,
    body: RefreshTokenRequest,
):
    """
    Refresh access token using a valid refresh token.

    Refresh tokens are single-use. Each call issues a new access/refresh pair,
    and the old refresh token is immediately revoked. Attempting to reuse a
    refresh token will be rejected as revoked (replay attack detection).
    """
    token_manager = _get_token_manager(request)

    try:
        token_data = token_manager.refresh_access_token(body.refresh_token)
        payload = TokenResponse(data=token_data)
        return JSONResponse(status_code=200, content=payload.model_dump())
    except JWTError as exc:
        status_code = getattr(exc, "status_code", 400)
        message = exc.message
        return _build_error_response(status_code, message)
    except Exception as exc:
        return _build_error_response(500, "Token refresh failed")