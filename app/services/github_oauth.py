from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from threading import Lock
from typing import Protocol
import base64
import os
import re
import secrets
import time
from urllib.parse import urlencode

from dotenv import load_dotenv

from httpx import AsyncClient, HTTPError, HTTPStatusError

from app.models.auth import GitHubIdentityData

load_dotenv()

GITHUB_AUTHORIZE_URL = os.getenv("GITHUB_AUTHORIZE_URL", "https://github.com/login/oauth/authorize")
GITHUB_TOKEN_URL = os.getenv("GITHUB_TOKEN_URL", "https://github.com/login/oauth/access_token")
GITHUB_USER_URL = os.getenv("GITHUB_USER_URL", "https://api.github.com/user")
DEFAULT_GITHUB_SCOPE = os.getenv("DEFAULT_GITHUB_SCOPE", "read:user user:email")
DEFAULT_STATE_TTL_SECONDS = int(os.getenv("DEFAULT_STATE_TTL_SECONDS", 600))


class GitHubOAuthError(Exception):
    status_code = 400


class InvalidCallbackCodeError(GitHubOAuthError):
    message = "Invalid callback code"


class InvalidOAuthStateError(GitHubOAuthError):
    message = "Invalid OAuth state"


class GitHubUpstreamError(GitHubOAuthError):
    status_code = 502


class OAuthStateStore(Protocol):
    def create(self, verifier: str, ttl_seconds: int) -> str:
        ...

    def consume(self, state: str) -> str | None:
        ...


@dataclass(slots=True)
class GitHubOAuthConfig:
    client_id: str
    client_secret: str | None = None
    scope: str = DEFAULT_GITHUB_SCOPE


@dataclass(slots=True)
class PKCEPair:
    verifier: str
    challenge: str


@dataclass(slots=True)
class GitHubAuthorizationRequest:
    state: str
    verifier: str
    redirect_url: str


@dataclass(slots=True)
class _OAuthStateRecord:
    verifier: str
    expires_at: float


class InMemoryOAuthStateStore:
    def __init__(self):
        self._lock = Lock()
        self._records: dict[str, _OAuthStateRecord] = {}

    def _purge_expired(self, now: float) -> None:
        expired = [state for state, record in self._records.items() if record.expires_at <= now]
        for state in expired:
            self._records.pop(state, None)

    def create(self, verifier: str, ttl_seconds: int) -> str:
        state = secrets.token_urlsafe(32)
        expires_at = time.time() + ttl_seconds
        with self._lock:
            self._purge_expired(time.time())
            self._records[state] = _OAuthStateRecord(verifier=verifier, expires_at=expires_at)
        return state

    def consume(self, state: str) -> str | None:
        with self._lock:
            now = time.time()
            self._purge_expired(now)
            record = self._records.pop(state, None)
            if record is None:
                return None
            if record.expires_at <= now:
                return None
            return record.verifier


class GitHubOAuthService:
    def __init__(
        self,
        client: AsyncClient,
        config: GitHubOAuthConfig,
        state_store: OAuthStateStore,
        *,
        state_ttl_seconds: int = DEFAULT_STATE_TTL_SECONDS,
    ):
        self._client = client
        self._config = config
        self._state_store = state_store
        self._state_ttl_seconds = state_ttl_seconds

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )

    @staticmethod
    def _pkce_challenge(verifier: str) -> str:
        digest = sha256(verifier.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    @staticmethod
    def generate_pkce_pair() -> PKCEPair:
        verifier = secrets.token_urlsafe(64)
        return PKCEPair(verifier=verifier, challenge=GitHubOAuthService._pkce_challenge(verifier))

    def build_authorization_request(self, callback_url: str) -> GitHubAuthorizationRequest:
        pair = self.generate_pkce_pair()
        state = self._state_store.create(pair.verifier, self._state_ttl_seconds)
        params = {
            "client_id": self._config.client_id,
            "redirect_uri": callback_url,
            "response_type": "code",
            "scope": self._config.scope,
            "state": state,
            "code_challenge": pair.challenge,
            "code_challenge_method": "S256",
        }
        redirect_url = f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}"
        return GitHubAuthorizationRequest(state=state, verifier=pair.verifier, redirect_url=redirect_url)

    async def _exchange_code_for_token(self, *, code: str, verifier: str, callback_url: str) -> dict:
        data = {
            "client_id": self._config.client_id,
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": callback_url,
        }
        if self._config.client_secret:
            data["client_secret"] = self._config.client_secret

        try:
            response = await self._client.post(
                GITHUB_TOKEN_URL,
                data=data,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            body = response.json()
        except HTTPStatusError as exc:
            if exc.response.status_code in {400, 401, 403}:
                raise InvalidCallbackCodeError(InvalidCallbackCodeError.message) from exc
            raise GitHubUpstreamError("GitHub token exchange failed") from exc
        except (HTTPError, ValueError, TypeError) as exc:
            raise GitHubUpstreamError("GitHub token exchange failed") from exc

        if not isinstance(body, dict):
            raise GitHubUpstreamError("GitHub token exchange returned an invalid payload")

        access_token = body.get("access_token")
        if not isinstance(access_token, str) or access_token.strip() == "":
            raise InvalidCallbackCodeError(InvalidCallbackCodeError.message)

        return body

    async def _fetch_user(self, access_token: str) -> dict:
        try:
            response = await self._client.get(
                GITHUB_USER_URL,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {access_token}",
                },
            )
            response.raise_for_status()
            body = response.json()
        except (HTTPError, ValueError, TypeError) as exc:
            raise GitHubUpstreamError("GitHub user lookup failed") from exc

        if not isinstance(body, dict):
            raise GitHubUpstreamError("GitHub user lookup returned an invalid payload")

        return body

    @staticmethod
    def _require_non_empty_str(value: object, message: str) -> str:
        if not isinstance(value, str) or value.strip() == "":
            raise GitHubUpstreamError(message)
        return value

    @staticmethod
    def _optional_text(value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return str(value)

    @staticmethod
    def _parse_scope(scope_value: object) -> list[str]:
        if isinstance(scope_value, str):
            return [item for item in re.split(r"[\s,]+", scope_value.strip()) if item]
        return []

    def _build_identity_data(self, token_body: dict, user_body: dict) -> GitHubIdentityData:
        try:
            github_id = int(user_body["id"])
            login = self._require_non_empty_str(user_body["login"], "GitHub user lookup returned an incomplete payload")
        except (KeyError, TypeError, ValueError) as exc:
            raise GitHubUpstreamError("GitHub user lookup returned an incomplete payload") from exc

        token_type = token_body.get("token_type")
        if not isinstance(token_type, str) or token_type.strip() == "":
            token_type = "bearer"

        return GitHubIdentityData(
            github_id=github_id,
            login=login,
            name=self._optional_text(user_body.get("name")),
            email=self._optional_text(user_body.get("email")),
            avatar_url=self._optional_text(user_body.get("avatar_url")),
            html_url=self._optional_text(user_body.get("html_url")),
            token_type=token_type.lower(),
            scope=self._parse_scope(token_body.get("scope")),
            processed_at=self._utc_now_iso(),
        )

    async def exchange_code(self, *, code: str | None, state: str | None, callback_url: str) -> GitHubIdentityData:
        if not isinstance(code, str) or code.strip() == "":
            raise InvalidCallbackCodeError(InvalidCallbackCodeError.message)

        if not isinstance(state, str) or state.strip() == "":
            raise InvalidOAuthStateError(InvalidOAuthStateError.message)

        verifier = self._state_store.consume(state)
        if verifier is None:
            raise InvalidOAuthStateError(InvalidOAuthStateError.message)

        token_body = await self._exchange_code_for_token(
            code=code,
            verifier=verifier,
            callback_url=callback_url,
        )
        user_body = await self._fetch_user(str(token_body["access_token"]))
        return self._build_identity_data(token_body, user_body)


def get_github_oauth_config() -> GitHubOAuthConfig:
    client_id = os.getenv("GITHUB_CLIENT_ID")
    if not client_id:
        raise RuntimeError("GITHUB_CLIENT_ID is required")

    return GitHubOAuthConfig(
        client_id=client_id,
        client_secret=os.getenv("GITHUB_CLIENT_SECRET"),
        scope=os.getenv("GITHUB_OAUTH_SCOPE", DEFAULT_GITHUB_SCOPE),
    )