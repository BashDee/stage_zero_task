from __future__ import annotations

from typing import Optional

from supabase import Client


class TokenRepository:
    """Manages refresh token JTI storage and revocation state in Supabase."""

    TABLE_NAME = "tokens"

    def __init__(self, supabase_client: Client):
        self._client = supabase_client

    def store_refresh_token_jti(
        self,
        jti: str,
        github_id: int,
        expires_at: int,
        token_type: str = "refresh",
    ) -> None:
        """
        Store refresh token JTI in database for revocation tracking.

        Args:
            jti: JWT ID (unique identifier for this token)
            github_id: GitHub user ID
            expires_at: Unix timestamp when token expires
            token_type: "refresh" or "access" (default "refresh")
        """
        self._client.table(self.TABLE_NAME).insert(
            {
                "jti": jti,
                "github_id": github_id,
                "token_type": token_type,
                "expires_at": expires_at,
                "is_revoked": False,
            }
        ).execute()

    def is_jti_revoked(self, jti: str) -> bool:
        """
        Check if a refresh token JTI has been revoked.

        Args:
            jti: JWT ID to check

        Returns:
            True if token is revoked; False if valid or not found
        """
        try:
            response = self._client.table(self.TABLE_NAME).select("is_revoked").eq("jti", jti).single().execute()
            return bool(response.data.get("is_revoked", False))
        except Exception:
            # If not found or error, treat as revoked (fail secure)
            return True

    def revoke_jti(self, jti: str) -> None:
        """
        Revoke a refresh token by marking its JTI as revoked.

        Args:
            jti: JWT ID to revoke
        """
        self._client.table(self.TABLE_NAME).update({"is_revoked": True}).eq("jti", jti).execute()

    def cleanup_expired_tokens(self) -> int:
        """
        Delete expired token records from database.

        Returns:
            Number of records deleted
        """
        import time

        now = int(time.time())
        response = self._client.table(self.TABLE_NAME).delete().lte("expires_at", now).execute()
        # Supabase delete() doesn't directly return count, so we estimate from response
        return len(response.data) if response.data else 0
