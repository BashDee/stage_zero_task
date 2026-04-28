from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from httpx import Request, Response

import main
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
    monkeypatch.setenv("GITHUB_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(main, "init_db", lambda: None)

    with TestClient(main.app) as client:
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
    assert data["provider"] == "github"
    assert data["github_id"] == 42
    assert data["login"] == "octocat"
    assert data["name"] == "The Octocat"
    assert data["email"] == "octo@example.com"
    assert data["avatar_url"] == "https://avatars.example.com/octocat"
    assert data["html_url"] == "https://github.com/octocat"
    assert data["token_type"] == "bearer"
    assert data["scope"] == ["read:user", "user:email"]
    assert data["processed_at"].endswith("Z")


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