from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.repositories.users import UserRecord, UserRepository
from app.services.user_errors import UserNotFoundError, UserRepositoryError

logger = logging.getLogger(__name__)


class UserService:
    """Orchestrates user persistence and lifecycle management."""

    def __init__(self, repository: UserRepository):
        """
        Initialize service with user repository.

        Args:
            repository: UserRepository instance for data access
        """
        self._repo = repository

    @staticmethod
    def _utc_now_iso() -> str:
        """Get current UTC time as ISO-8601 string."""
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def get_or_create(
        self,
        github_id: int,
        username: str,
        email: str | None = None,
        avatar_url: str | None = None,
    ) -> UserRecord:
        """
        Retrieve user by GitHub ID or create if not exists.

        On callback:
        - If user exists and is_inactive → reactivate and log event
        - If user exists and is_active → update last_login_at
        - If not exists → create with default role='analyst'

        Args:
            github_id: GitHub user ID
            username: GitHub login name
            email: Optional email address
            avatar_url: Optional avatar URL

        Returns:
            UserRecord (existing or newly created)

        Raises:
            UserRepositoryError: If any repository operation fails
        """
        try:
            existing_user = self._repo.find_by_github_id(github_id)

            if existing_user is None:
                # New user: create with defaults
                logger.info(f"Creating new user: github_id={github_id}, username={username}")
                return self._repo.create(
                    github_id=github_id,
                    username=username,
                    email=email,
                    avatar_url=avatar_url,
                )

            # Existing user
            if not existing_user.is_active:
                # Reactivate inactive user
                logger.info(
                    f"Reactivating inactive user: github_id={github_id}, username={username}"
                )
                return self._repo.reactivate(github_id)
            else:
                # Active user: update last login
                now_iso = self._utc_now_iso()
                self._repo.update_last_login(github_id, now_iso)
                # Return updated record with new timestamp
                updated = self._repo.find_by_github_id(github_id)
                if updated is None:
                    raise UserRepositoryError("Failed to retrieve updated user record")
                return updated

        except (UserNotFoundError, UserRepositoryError):
            raise

    def enforce_active_status(self, user: UserRecord) -> None:
        """
        Verify user is active; raise if inactive.

        Args:
            user: UserRecord to check

        Raises:
            UserNotFoundError: If user is inactive (currently not used in callback flow)
        """
        if not user.is_active:
            raise UserNotFoundError("User account is inactive")
