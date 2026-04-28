from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, Mock, AsyncMock

import pytest
from fastapi.testclient import TestClient

import main
from app.models.token import RefreshTokenRequest, TokenData
from app.repositories.tokens import TokenRepository
from app.services.jwt import JWTService, DEFAULT_ACCESS_EXPIRY_SECONDS, DEFAULT_REFRESH_EXPIRY_SECONDS
from app.services.jwt_errors import (
    ExpiredTokenError,
    InvalidTokenError,
    RevokedTokenError,
)
from app.services.token_manager import TokenManager


# ==============================================================================
# Unit Tests: JWT Service
# ==============================================================================


class TestJWTService:
    """Unit tests for JWT token generation and validation."""

    @pytest.fixture
    def jwt_service(self):
        """Create a JWT service instance with test secret."""
        return JWTService(secret_key="test-secret-key-12345678")

    def test_generate_access_token_format(self, jwt_service):
        """Test that access tokens are properly formatted JWT strings."""
        token = jwt_service.generate_access_token(github_id=42, login="octocat")
        
        assert isinstance(token, str)
        assert token.count(".") == 2  # JWT format: header.payload.signature

    def test_generate_refresh_token_returns_token_and_jti(self, jwt_service):
        """Test that refresh tokens return both token and JTI."""
        token, jti = jwt_service.generate_refresh_token(github_id=42, login="octocat")
        
        assert isinstance(token, str)
        assert isinstance(jti, str)
        assert token.count(".") == 2
        assert len(jti) > 0

    def test_verify_access_token_validates_signature(self, jwt_service):
        """Test that access token validation checks signature."""
        token = jwt_service.generate_access_token(github_id=42, login="octocat")
        payload = jwt_service.verify_access_token(token)
        
        assert payload.sub == "42"  # sub is string in JWT
        assert payload.login == "octocat"
        assert payload.token_type == "access"
        assert payload.jti is not None

    def test_verify_refresh_token_validates_signature(self, jwt_service):
        """Test that refresh token validation checks signature."""
        token, expected_jti = jwt_service.generate_refresh_token(github_id=42, login="octocat")
        payload = jwt_service.verify_refresh_token(token)
        
        assert payload.sub == "42"  # sub is string in JWT
        assert payload.login == "octocat"
        assert payload.token_type == "refresh"
        assert payload.jti == expected_jti

    def test_verify_access_token_rejects_invalid_signature(self, jwt_service):
        """Test that modifying token signature causes validation to fail."""
        token = jwt_service.generate_access_token(github_id=42, login="octocat")
        tampered_token = token[:-5] + "xxxxx"  # Corrupt signature
        
        with pytest.raises(InvalidTokenError):
            jwt_service.verify_access_token(tampered_token)

    def test_verify_access_token_rejects_malformed_token(self, jwt_service):
        """Test that malformed tokens are rejected."""
        with pytest.raises(InvalidTokenError):
            jwt_service.verify_access_token("not.a.jwt")

    def test_verify_access_token_rejects_expired_token(self, jwt_service):
        """Test that expired tokens raise ExpiredTokenError."""
        jwt_service_short = JWTService(
            secret_key="test-secret-key-12345678",
            access_expiry_seconds=1,
        )
        token = jwt_service_short.generate_access_token(github_id=42, login="octocat")
        
        time.sleep(2)  # Wait for token to expire
        
        with pytest.raises(ExpiredTokenError):
            jwt_service_short.verify_access_token(token)

    def test_verify_refresh_token_rejects_expired_token(self, jwt_service):
        """Test that expired refresh tokens raise ExpiredTokenError."""
        jwt_service_short = JWTService(
            secret_key="test-secret-key-12345678",
            refresh_expiry_seconds=1,
        )
        token, jti = jwt_service_short.generate_refresh_token(github_id=42, login="octocat")
        
        time.sleep(2)  # Wait for token to expire
        
        with pytest.raises(ExpiredTokenError):
            jwt_service_short.verify_refresh_token(token)

    def test_access_token_expires_in_3_minutes(self, jwt_service):
        """Test that access tokens have correct default expiry."""
        token = jwt_service.generate_access_token(github_id=42, login="octocat")
        payload = jwt_service.verify_access_token(token)
        
        now = int(time.time())
        expected_expiry = now + DEFAULT_ACCESS_EXPIRY_SECONDS
        # Allow 2-second drift for test execution
        assert abs(payload.exp - expected_expiry) <= 2

    def test_refresh_token_expires_in_5_minutes(self, jwt_service):
        """Test that refresh tokens have correct default expiry."""
        token, jti = jwt_service.generate_refresh_token(github_id=42, login="octocat")
        payload = jwt_service.verify_refresh_token(token)
        
        now = int(time.time())
        expected_expiry = now + DEFAULT_REFRESH_EXPIRY_SECONDS
        # Allow 2-second drift for test execution
        assert abs(payload.exp - expected_expiry) <= 2


# ==============================================================================
# Unit Tests: Token Repository
# ==============================================================================


class TestTokenRepository:
    """Unit tests for token JTI storage and revocation."""

    @pytest.fixture
    def mock_supabase_client(self):
        """Create a mock Supabase client."""
        return MagicMock()

    @pytest.fixture
    def token_repository(self, mock_supabase_client):
        """Create a token repository with mocked Supabase."""
        return TokenRepository(mock_supabase_client)

    def test_store_refresh_token_jti_inserts_record(self, token_repository, mock_supabase_client):
        """Test that storing a JTI inserts a record in the database."""
        mock_table = MagicMock()
        mock_supabase_client.table.return_value = mock_table
        mock_table.insert.return_value = mock_table
        mock_table.execute.return_value = {"data": [{"jti": "test-jti"}]}
        
        token_repository.store_refresh_token_jti(
            jti="test-jti",
            github_id=42,
            expires_at=int(time.time()) + 300,
        )
        
        mock_supabase_client.table.assert_called_with("tokens")
        mock_table.insert.assert_called_once()
        call_args = mock_table.insert.call_args[0][0]
        assert call_args["jti"] == "test-jti"
        assert call_args["github_id"] == 42
        assert call_args["is_revoked"] is False

    def test_is_jti_revoked_returns_false_for_valid_token(self, token_repository, mock_supabase_client):
        """Test that valid tokens are not marked as revoked."""
        mock_table = MagicMock()
        mock_supabase_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.single.return_value = mock_table
        mock_table.execute.return_value = Mock(data={"is_revoked": False})
        
        result = token_repository.is_jti_revoked("test-jti")
        
        assert result is False

    def test_is_jti_revoked_returns_true_for_revoked_token(self, token_repository, mock_supabase_client):
        """Test that revoked tokens are correctly identified."""
        mock_table = MagicMock()
        mock_supabase_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.single.return_value = mock_table
        mock_table.execute.return_value = Mock(data={"is_revoked": True})
        
        result = token_repository.is_jti_revoked("test-jti")
        
        assert result is True

    def test_is_jti_revoked_returns_true_on_not_found(self, token_repository, mock_supabase_client):
        """Test that missing JTIs are treated as revoked (fail-secure)."""
        mock_table = MagicMock()
        mock_supabase_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.single.return_value = mock_table
        mock_table.execute.side_effect = Exception("Not found")
        
        result = token_repository.is_jti_revoked("nonexistent-jti")
        
        assert result is True  # Fail-secure: treat missing as revoked

    def test_revoke_jti_updates_database(self, token_repository, mock_supabase_client):
        """Test that revoking a JTI updates the database."""
        mock_table = MagicMock()
        mock_supabase_client.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.return_value = {}
        
        token_repository.revoke_jti("test-jti")
        
        mock_supabase_client.table.assert_called_with("tokens")
        mock_table.update.assert_called_once_with({"is_revoked": True})
        mock_table.eq.assert_called_with("jti", "test-jti")


# ==============================================================================
# Integration Tests: Token Manager
# ==============================================================================


class TestTokenManager:
    """Integration tests for token issuance and refresh with rotation."""

    @pytest.fixture
    def jwt_service(self):
        return JWTService(secret_key="test-secret-key-12345678")

    @pytest.fixture
    def mock_token_repository(self):
        """Create a mock token repository."""
        repo = MagicMock(spec=TokenRepository)
        repo.is_jti_revoked.return_value = False
        return repo

    @pytest.fixture
    def token_manager(self, jwt_service, mock_token_repository):
        return TokenManager(jwt_service, mock_token_repository)

    def test_issue_tokens_returns_valid_pair(self, token_manager, mock_token_repository):
        """Test that issue_tokens returns both access and refresh tokens."""
        token_data = token_manager.issue_tokens(github_id=42, login="octocat")
        
        assert isinstance(token_data, TokenData)
        assert len(token_data.access_token) > 0
        assert len(token_data.refresh_token) > 0
        assert token_data.token_type == "bearer"
        assert token_data.expires_in == DEFAULT_ACCESS_EXPIRY_SECONDS
        
        # Verify JTI was stored
        mock_token_repository.store_refresh_token_jti.assert_called_once()

    def test_refresh_access_token_validates_refresh_token(self, token_manager, jwt_service, mock_token_repository):
        """Test that refresh endpoint validates the refresh token."""
        # Issue initial tokens
        first_pair = token_manager.issue_tokens(github_id=42, login="octocat")
        
        # Use the refresh token to get new pair
        second_pair = token_manager.refresh_access_token(first_pair.refresh_token)
        
        assert isinstance(second_pair, TokenData)
        assert len(second_pair.access_token) > 0
        assert len(second_pair.refresh_token) > 0
        assert second_pair.access_token != first_pair.access_token
        assert second_pair.refresh_token != first_pair.refresh_token

    def test_refresh_rejects_expired_token(self, token_manager, jwt_service):
        """Test that expired refresh tokens are rejected."""
        jwt_service_short = JWTService(
            secret_key="test-secret-key-12345678",
            refresh_expiry_seconds=1,
        )
        
        mock_repo = MagicMock(spec=TokenRepository)
        mock_repo.is_jti_revoked.return_value = False
        
        manager_short = TokenManager(jwt_service_short, mock_repo)
        
        # Issue token
        pair = manager_short.issue_tokens(github_id=42, login="octocat")
        
        # Wait for expiry
        time.sleep(2)
        
        # Attempt to refresh
        with pytest.raises(ExpiredTokenError):
            manager_short.refresh_access_token(pair.refresh_token)

    def test_refresh_rejects_revoked_token(self, token_manager, mock_token_repository):
        """Test that revoked refresh tokens are rejected."""
        pair = token_manager.issue_tokens(github_id=42, login="octocat")
        
        # Mark token as revoked
        mock_token_repository.is_jti_revoked.return_value = True
        
        with pytest.raises(RevokedTokenError):
            token_manager.refresh_access_token(pair.refresh_token)

    def test_refresh_revokes_old_token_immediately(self, token_manager, mock_token_repository):
        """Test that old refresh token is revoked after rotation."""
        pair = token_manager.issue_tokens(github_id=42, login="octocat")
        
        # Extract JTI from initial token (simulate)
        initial_jti_call_args = mock_token_repository.store_refresh_token_jti.call_args
        initial_jti = initial_jti_call_args[1]["jti"]
        
        # Reset mock to track second call
        mock_token_repository.reset_mock()
        mock_token_repository.is_jti_revoked.return_value = False
        
        # Refresh the token
        new_pair = token_manager.refresh_access_token(pair.refresh_token)
        
        # Verify old JTI was revoked
        mock_token_repository.revoke_jti.assert_called_once()

    def test_refresh_detects_replay_attack(self, token_manager, mock_token_repository):
        """Test that reusing a refresh token is detected as replay attack."""
        pair = token_manager.issue_tokens(github_id=42, login="octocat")
        
        # First use succeeds
        mock_token_repository.is_jti_revoked.return_value = False
        new_pair = token_manager.refresh_access_token(pair.refresh_token)
        
        # Mark token as revoked after first use
        mock_token_repository.is_jti_revoked.return_value = True
        
        # Second use fails (replay attack)
        with pytest.raises(RevokedTokenError):
            token_manager.refresh_access_token(pair.refresh_token)


# ==============================================================================
# Integration Tests: Callback and Refresh Endpoints
# ==============================================================================


@pytest.fixture
def auth_client(monkeypatch):
    """Create a test client with mocked GitHub OAuth."""
    monkeypatch.setenv("GITHUB_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-key-12345678")
    monkeypatch.setattr(main, "init_db", lambda: None)
    
    # Mock the Supabase client initialization
    def mock_get_supabase_client():
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table
        mock_table.insert.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.single.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.execute.return_value = Mock(data={"is_revoked": False})
        return mock_client
    
    monkeypatch.setattr("app.db.get_supabase_client", mock_get_supabase_client)
    
    with TestClient(main.app) as client:
        yield client


def test_github_callback_issues_tokens(auth_client):
    """Test that GitHub callback successfully issues tokens."""
    from urllib.parse import parse_qs, urlparse
    
    async def fake_post(url, **kwargs):
        await asyncio.sleep(0)
        return Mock(
            status_code=200,
            json=lambda: {
                "access_token": "github-token-123",
                "token_type": "bearer",
                "scope": "read:user user:email",
            },
            raise_for_status=lambda: None,
            request=Mock(),
        )
    
    async def fake_get(url, **kwargs):
        await asyncio.sleep(0)
        return Mock(
            status_code=200,
            json=lambda: {
                "id": 42,
                "login": "octocat",
                "name": "The Octocat",
            },
            raise_for_status=lambda: None,
            request=Mock(),
        )
    
    auth_client.app.state.http_client.post = fake_post
    auth_client.app.state.http_client.get = fake_get
    
    # Start GitHub auth flow
    start_response = auth_client.get("/auth/github", follow_redirects=False)
    state = parse_qs(urlparse(start_response.headers["location"]).query)["state"][0]
    
    # Callback with tokens
    response = auth_client.get(f"/auth/github/callback?code=valid-code&state={state}")
    
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert "access_token" in payload["data"]
    assert "refresh_token" in payload["data"]
    assert payload["data"]["token_type"] == "bearer"
    assert payload["data"]["expires_in"] == DEFAULT_ACCESS_EXPIRY_SECONDS


def test_refresh_endpoint_issues_new_tokens(auth_client):
    """Test that /auth/refresh endpoint issues new token pair."""
    from app.models.token import RefreshTokenRequest
    import json
    
    # Issue initial tokens directly via token manager
    jwt_service = auth_client.app.state.jwt_service
    token_manager = auth_client.app.state.token_manager
    
    initial_pair = token_manager.issue_tokens(github_id=42, login="octocat")
    
    # Call refresh endpoint
    response = auth_client.post(
        "/auth/refresh",
        content=json.dumps({"refresh_token": initial_pair.refresh_token}),
        headers={"Content-Type": "application/json"},
    )
    
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert "access_token" in payload["data"]
    assert "refresh_token" in payload["data"]
    assert payload["data"]["access_token"] != initial_pair.access_token
    assert payload["data"]["refresh_token"] != initial_pair.refresh_token


def test_refresh_endpoint_rejects_invalid_token(auth_client):
    """Test that /auth/refresh rejects invalid tokens."""
    import json
    
    response = auth_client.post(
        "/auth/refresh",
        content=json.dumps({"refresh_token": "invalid.token.here"}),
        headers={"Content-Type": "application/json"},
    )
    
    assert response.status_code == 401
    payload = response.json()
    assert payload["status"] == "error"
    assert "Invalid token" in payload["message"] or "expired" in payload["message"].lower()


def test_refresh_endpoint_rejects_missing_token(auth_client):
    """Test that /auth/refresh rejects missing token."""
    import json
    
    response = auth_client.post(
        "/auth/refresh",
        content=json.dumps({"refresh_token": ""}),
        headers={"Content-Type": "application/json"},
    )
    
    assert response.status_code in (400, 401)
