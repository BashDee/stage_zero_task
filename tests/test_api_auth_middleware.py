from __future__ import annotations

import time
from dataclasses import asdict

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.middleware.auth import AccessTokenAuthMiddleware
from app.repositories.users import UserRecord
from app.services.jwt import JWTService


class _StubUserRepository:
    def __init__(self, user: UserRecord | None):
        self._user = user

    def find_by_github_id(self, github_id: int) -> UserRecord | None:
        return self._user


def _build_test_app(*, jwt_service: JWTService, user: UserRecord | None) -> FastAPI:
    app = FastAPI()
    app.state.jwt_service = jwt_service
    app.state.user_repository = _StubUserRepository(user)
    app.add_middleware(AccessTokenAuthMiddleware)

    @app.get("/api/context")
    async def get_context(request: Request):
        return {"status": "success", "data": asdict(request.state.user)}

    @app.get("/auth/ping")
    async def ping():
        return {"status": "success"}

    return app


def _active_user() -> UserRecord:
    return UserRecord(
        id="550e8400-e29b-41d4-a716-446655440000",
        github_id=42,
        username="octocat",
        email="octo@example.com",
        avatar_url="https://avatars.example.com/octocat",
        role="analyst",
        is_active=True,
        last_login_at=None,
        created_at="2026-04-01T00:00:00Z",
    )


def test_auth_middleware_missing_token_returns_401():
    app = _build_test_app(jwt_service=JWTService(secret_key="test-secret-key"), user=_active_user())
    with TestClient(app) as client:
        response = client.get("/api/context")

    assert response.status_code == 401
    assert response.json() == {"status": "error", "message": "Missing access token"}


def test_auth_middleware_invalid_token_returns_401():
    app = _build_test_app(jwt_service=JWTService(secret_key="test-secret-key"), user=_active_user())
    with TestClient(app) as client:
        response = client.get("/api/context", headers={"Authorization": "Bearer not.a.jwt"})

    assert response.status_code == 401
    assert response.json() == {"status": "error", "message": "Invalid token"}


def test_auth_middleware_expired_token_returns_401():
    jwt_service = JWTService(secret_key="test-secret-key", access_expiry_seconds=1)
    app = _build_test_app(jwt_service=jwt_service, user=_active_user())
    token = jwt_service.generate_access_token(github_id=42, login="octocat")
    time.sleep(2)

    with TestClient(app) as client:
        response = client.get("/api/context", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json() == {"status": "error", "message": "Token expired"}


def test_auth_middleware_blocks_inactive_user_with_403():
    jwt_service = JWTService(secret_key="test-secret-key")
    inactive_user = _active_user()
    inactive_user.is_active = False
    app = _build_test_app(jwt_service=jwt_service, user=inactive_user)
    token = jwt_service.generate_access_token(github_id=42, login="octocat")

    with TestClient(app) as client:
        response = client.get("/api/context", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    assert response.json() == {"status": "error", "message": "User account is inactive"}


def test_auth_middleware_attaches_user_context():
    jwt_service = JWTService(secret_key="test-secret-key")
    app = _build_test_app(jwt_service=jwt_service, user=_active_user())
    token = jwt_service.generate_access_token(github_id=42, login="octocat")

    with TestClient(app) as client:
        response = client.get("/api/context", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "data": {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "role": "analyst",
            "is_active": True,
        },
    }


def test_auth_middleware_does_not_protect_auth_routes():
    app = _build_test_app(jwt_service=JWTService(secret_key="test-secret-key"), user=_active_user())
    with TestClient(app) as client:
        response = client.get("/auth/ping")

    assert response.status_code == 200
    assert response.json() == {"status": "success"}
