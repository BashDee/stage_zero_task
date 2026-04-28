from __future__ import annotations

import asyncio
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from httpx import Request, Response

import main
from app.repositories.users import UserRecord
from app.services.github_oauth import (
    GitHubOAuthService,
    GitHubOAuthConfig,
    InMemoryOAuthStateStore,
)


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200, method: str = "GET", url: str = "https://example.com"):
        self._payload = payload
        self.status_code = status_code
        self.request = Request(method, url)

    def raise_for_status(self) -> None:
        response = Response(self.status_code, request=self.request)
        response.raise_for_status()

    def json(self) -> dict:
        return self._payload


@pytest.fixture()
def auth_client(monkeypatch):
    from app.services.users import UserService
    
    monkeypatch.setenv("GITHUB_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "test-key")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(main, "init_db", lambda: None)
    
    # Create mock Supabase client
    mock_supabase_client = Mock()
    monkeypatch.setattr("app.db.get_supabase_client", lambda: mock_supabase_client)

    with TestClient(main.app) as client:
        # Create a mock UserService that returns test user
        mock_user_service = Mock(spec=UserService)
        test_user = UserRecord(
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
        mock_user_service.get_or_create.return_value = test_user
        # Inject the mock UserService after app initialization
        client.app.state.user_service = mock_user_service
        yield client


def test_generate_pkce_pair_is_valid():
    service = GitHubOAuthService(
        client=None,  # type: ignore[arg-type]
        config=GitHubOAuthConfig(client_id="test-client-id"),
        state_store=InMemoryOAuthStateStore(),
    )

    pair = service.generate_pkce_pair()

    assert 43 <= len(pair.verifier) <= 128
    assert 43 <= len(pair.challenge) <= 128
    assert pair.verifier != pair.challenge


def test_github_login_redirects_with_pkce(auth_client):
    response = auth_client.get("/auth/github", follow_redirects=False)

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)

    assert parsed.netloc == "github.com"
    assert parsed.path == "/login/oauth/authorize"
    assert query["client_id"] == ["test-client-id"]
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"][0]
    assert query["code_challenge"][0]


def test_github_callback_exchanges_code_and_returns_identity(auth_client):
    async def fake_post(url, **kwargs):
        await asyncio.sleep(0)
        return FakeResponse(
            {"access_token": "token-123", "token_type": "bearer", "scope": "read:user user:email"},
            method="POST",
            url=url,
        )

    async def fake_get(url, **kwargs):
        await asyncio.sleep(0)
        return FakeResponse(
            {
                "id": 42,
                "login": "octocat",
                "name": "The Octocat",
                "email": "octo@example.com",
                "avatar_url": "https://avatars.example.com/octocat",
                "html_url": "https://github.com/octocat",
            },
            method="GET",
            url=url,
        )

    auth_client.app.state.http_client.post = fake_post
    auth_client.app.state.http_client.get = fake_get

    start_response = auth_client.get("/auth/github", follow_redirects=False)
    state = parse_qs(urlparse(start_response.headers["location"]).query)["state"][0]

    response = auth_client.get(f"/auth/github/callback?code=valid-code&state={state}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    data = payload["data"]
    # Verify token response fields
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0


@pytest.mark.parametrize(
    "query, expected_status, expected_message",
    [
        ("/auth/github/callback", 400, "Invalid callback code"),
        ("/auth/github/callback?code=valid-code", 400, "Invalid OAuth state"),
    ],
)
def test_github_callback_validation_errors(auth_client, query, expected_status, expected_message):
    response = auth_client.get(query)

    assert response.status_code == expected_status
    assert response.json() == {"status": "error", "message": expected_message}


def test_github_callback_rejects_replayed_state(auth_client):
    async def fake_post(url, **kwargs):
        await asyncio.sleep(0)
        return FakeResponse(
            {"access_token": "token-123", "token_type": "bearer", "scope": "read:user"},
            method="POST",
            url=url,
        )

    async def fake_get(url, **kwargs):
        await asyncio.sleep(0)
        return FakeResponse(
            {"id": 42, "login": "octocat"},
            method="GET",
            url=url,
        )

    auth_client.app.state.http_client.post = fake_post
    auth_client.app.state.http_client.get = fake_get

    start_response = auth_client.get("/auth/github", follow_redirects=False)
    state = parse_qs(urlparse(start_response.headers["location"]).query)["state"][0]

    first = auth_client.get(f"/auth/github/callback?code=valid-code&state={state}")
    second = auth_client.get(f"/auth/github/callback?code=valid-code&state={state}")

    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json() == {"status": "error", "message": "Invalid OAuth state"}


def test_github_callback_maps_token_exchange_failure_to_invalid_code(auth_client):
    async def fake_post(url, **kwargs):
        await asyncio.sleep(0)
        return FakeResponse(
            {"error": "bad_verification_code"},
            status_code=400,
            method="POST",
            url=url,
        )

    auth_client.app.state.http_client.post = fake_post

    start_response = auth_client.get("/auth/github", follow_redirects=False)
    state = parse_qs(urlparse(start_response.headers["location"]).query)["state"][0]

    response = auth_client.get(f"/auth/github/callback?code=bad-code&state={state}")

    assert response.status_code == 400
    assert response.json() == {"status": "error", "message": "Invalid callback code"}


def test_github_callback_maps_user_lookup_failure_to_upstream_error(auth_client):
    async def fake_post(url, **kwargs):
        await asyncio.sleep(0)
        return FakeResponse(
            {"access_token": "token-123", "token_type": "bearer", "scope": "read:user"},
            method="POST",
            url=url,
        )

    async def fake_get(url, **kwargs):
        await asyncio.sleep(0)
        return FakeResponse(
            {"message": "server error"},
            status_code=500,
            method="GET",
            url=url,
        )

    auth_client.app.state.http_client.post = fake_post
    auth_client.app.state.http_client.get = fake_get

    start_response = auth_client.get("/auth/github", follow_redirects=False)
    state = parse_qs(urlparse(start_response.headers["location"]).query)["state"][0]

    response = auth_client.get(f"/auth/github/callback?code=valid-code&state={state}")

    assert response.status_code == 502
    assert response.json() == {"status": "error", "message": "GitHub user lookup failed"}