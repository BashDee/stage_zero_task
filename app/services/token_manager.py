from __future__ import annotations

from app.models.token import TokenData
from app.repositories.tokens import TokenRepository
from app.services.jwt import JWTService
from app.services.jwt_errors import RevokedTokenError


class TokenManager:
    """Orchestrates token issuance, validation, and refresh with replay protection."""

    def __init__(self, jwt_service: JWTService, token_repository: TokenRepository):
        self._jwt = jwt_service
        self._repo = token_repository

    def issue_tokens(self, github_id: int, login: str) -> TokenData:
        """
        Issue a new access and refresh token pair.

        Args:
            github_id: GitHub user ID
            login: GitHub login name

        Returns:
            TokenData with both access and refresh tokens
        """
        # Generate tokens
        access_token = self._jwt.generate_access_token(github_id, login)
        refresh_token, refresh_jti = self._jwt.generate_refresh_token(github_id, login)

        # Store refresh token JTI for revocation tracking
        expires_at = self._jwt.get_token_expiry_timestamp(github_id, "refresh")
        self._repo.store_refresh_token_jti(
            jti=refresh_jti,
            github_id=github_id,
            expires_at=expires_at,
            token_type="refresh",
        )

        return TokenData(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self._jwt._access_expiry_seconds,
        )

    def refresh_access_token(self, refresh_token: str) -> TokenData:
        """
        Validate refresh token, issue new token pair, rotate and revoke old token.

        Implements replay detection: if a refresh token is reused (already revoked),
        raises RevokedTokenError.

        Args:
            refresh_token: Client's current refresh token

        Returns:
            TokenData with new access and refresh tokens

        Raises:
            InvalidTokenError: Token signature/format invalid
            ExpiredTokenError: Token has expired
            RevokedTokenError: Token already used (replay attack) or already revoked
        """
        # Verify token signature and expiry
        payload = self._jwt.verify_refresh_token(refresh_token)

        # Extract the JTI and check if already revoked (replay detection)
        jti = payload.jti
        if self._repo.is_jti_revoked(jti):
            raise RevokedTokenError("Token revoked or already used")

        # Issue new token pair
        github_id = int(payload.sub)  # Convert sub from string back to int
        login = payload.login
        new_token_data = self.issue_tokens(github_id, login)

        # Revoke the old refresh token immediately after issuing new pair
        self._repo.revoke_jti(jti)

        return new_token_data
