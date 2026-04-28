from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from supabase import Client

from app.services.user_errors import UserNotFoundError, UserRepositoryError


@dataclass(slots=True)
class UserRecord:
    """Represents a user database row."""
    id: str
    github_id: int
    username: str
    email: str | None
    avatar_url: str | None
    role: str
    is_active: bool
    last_login_at: str | None
    created_at: str


class UserRepository:
    """Handles user persistence and retrieval from Supabase."""

    def __init__(self, client: Client):
        """
        Initialize repository with Supabase client.

        Args:
            client: Supabase client instance for database access
        """
        self._client = client

    @staticmethod
    def _map_row(row: dict) -> UserRecord:
        """Map a Supabase row to UserRecord dataclass."""
        return UserRecord(
            id=row["id"],
            github_id=row["github_id"],
            username=row["username"],
            email=row.get("email"),
            avatar_url=row.get("avatar_url"),
            role=row["role"],
            is_active=row["is_active"],
            last_login_at=row.get("last_login_at"),
            created_at=row["created_at"],
        )

    def find_by_github_id(self, github_id: int) -> UserRecord | None:
        """
        Retrieve user by GitHub ID.

        Args:
            github_id: GitHub user ID

        Returns:
            UserRecord if found, None otherwise

        Raises:
            UserRepositoryError: If database query fails
        """
        try:
            response = (
                self._client.table("users")
                .select("*")
                .eq("github_id", github_id)
                .execute()
            )
            if response.data and len(response.data) > 0:
                return self._map_row(response.data[0])
            return None
        except Exception as exc:
            raise UserRepositoryError(f"Failed to query user by github_id: {str(exc)}") from exc

    def create(
        self,
        github_id: int,
        username: str,
        email: str | None = None,
        avatar_url: str | None = None,
    ) -> UserRecord:
        """
        Create a new user with default role and active status.

        Args:
            github_id: GitHub user ID (must be unique)
            username: GitHub login name
            email: Optional email address
            avatar_url: Optional avatar URL

        Returns:
            Created UserRecord

        Raises:
            UserRepositoryError: If user creation fails
        """
        try:
            now_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            response = (
                self._client.table("users")
                .insert({
                    "github_id": github_id,
                    "username": username,
                    "email": email,
                    "avatar_url": avatar_url,
                    "role": "analyst",
                    "is_active": True,
                    "created_at": now_utc,
                })
                .execute()
            )
            if response.data and len(response.data) > 0:
                return self._map_row(response.data[0])
            raise UserRepositoryError("Create returned no data")
        except Exception as exc:
            raise UserRepositoryError(f"Failed to create user: {str(exc)}") from exc

    def update_last_login(self, github_id: int, timestamp: str) -> None:
        """
        Update last login timestamp for a user.

        Args:
            github_id: GitHub user ID
            timestamp: ISO-8601 UTC timestamp

        Raises:
            UserRepositoryError: If update fails
        """
        try:
            self._client.table("users").update(
                {"last_login_at": timestamp}
            ).eq("github_id", github_id).execute()
        except Exception as exc:
            raise UserRepositoryError(f"Failed to update last_login_at: {str(exc)}") from exc

    def reactivate(self, github_id: int) -> UserRecord:
        """
        Reactivate an inactive user account.

        Args:
            github_id: GitHub user ID

        Returns:
            Updated UserRecord with is_active=true

        Raises:
            UserNotFoundError: If user does not exist
            UserRepositoryError: If update fails
        """
        try:
            now_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            response = (
                self._client.table("users")
                .update({"is_active": True, "last_login_at": now_utc})
                .eq("github_id", github_id)
                .execute()
            )
            if response.data and len(response.data) > 0:
                return self._map_row(response.data[0])
            raise UserNotFoundError(f"User with github_id={github_id} not found")
        except UserNotFoundError:
            raise
        except Exception as exc:
            raise UserRepositoryError(f"Failed to reactivate user: {str(exc)}") from exc
