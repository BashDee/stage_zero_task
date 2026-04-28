from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.models.auth import GitHubIdentityResponse
from app.models.classify import ErrorResponse
from app.services.github_oauth import (
    GitHubOAuthError,
    GitHubOAuthService,
    InMemoryOAuthStateStore,
    get_github_oauth_config,
)


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


@router.get("/github")
async def github_login(request: Request):
    service = _get_service(request)
    callback_url = str(request.url_for("github_callback"))
    authorization = service.build_authorization_request(callback_url)
    return RedirectResponse(url=authorization.redirect_url, status_code=302)


@router.get(
    "/github/callback",
    name="github_callback",
    response_model=GitHubIdentityResponse | ErrorResponse,
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
    callback_url = str(request.url_for("github_callback"))

    try:
        identity = await service.exchange_code(code=code, state=state, callback_url=callback_url)
    except GitHubOAuthError as exc:
        message = getattr(exc, "message", str(exc))
        status_code = getattr(exc, "status_code", 400)
        return _build_error_response(status_code, message)

    payload = GitHubIdentityResponse(data=identity)
    return JSONResponse(status_code=200, content=payload.model_dump())