from __future__ import annotations


class UserError(Exception):
    """Base exception for user-related errors."""
    pass


class UserNotFoundError(UserError):
    """Raised when a user lookup fails."""
    message = "User not found"

    def __init__(self, message: str | None = None):
        super().__init__(message or self.message)


class UserInactiveError(UserError):
    """Raised when attempting to authenticate as an inactive user."""
    message = "User account is inactive"

    def __init__(self, message: str | None = None):
        super().__init__(message or self.message)


class UserRepositoryError(UserError):
    """Raised for repository-level persistence errors."""
    message = "Failed to access user repository"

    def __init__(self, message: str | None = None):
        super().__init__(message or self.message)
