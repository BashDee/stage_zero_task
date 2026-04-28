from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from app.repositories.users import UserRecord
from app.services.users import UserService
from app.services.user_errors import UserNotFoundError, UserRepositoryError


@pytest.fixture
def mock_repository():
    """Create a mocked UserRepository."""
    return Mock()


@pytest.fixture
def user_service(mock_repository):
    """Create a UserService with mocked repository."""
    return UserService(mock_repository)


@pytest.fixture
def sample_user_record():
    """Create a sample UserRecord for testing."""
    return UserRecord(
        id="550e8400-e29b-41d4-a716-446655440000",
        github_id=42,
        username="octocat",
        email="octo@example.com",
        avatar_url="https://avatars.example.com/octocat",
        role="analyst",
        is_active=True,
        last_login_at="2026-04-28T12:00:00Z",
        created_at="2026-04-01T12:00:00Z",
    )


def test_unique_github_id_enforcement(user_service, mock_repository, sample_user_record):
    """Test that duplicate GitHub IDs are handled correctly (existing user reused)."""
    # First call returns existing user
    mock_repository.find_by_github_id.return_value = sample_user_record
    mock_repository.update_last_login.return_value = None

    # Call get_or_create twice with same github_id
    result1 = user_service.get_or_create(
        github_id=42,
        username="octocat",
        email="octo@example.com",
        avatar_url="https://avatars.example.com/octocat",
    )
    result2 = user_service.get_or_create(
        github_id=42,
        username="octocat",
        email="octo@example.com",
        avatar_url="https://avatars.example.com/octocat",
    )

    # Verify create was never called (unique constraint maintained)
    assert mock_repository.create.call_count == 0
    # Verify find_by_github_id was called 4 times:
    # - 2 calls per get_or_create (once to check existence, once after updating last_login)
    assert mock_repository.find_by_github_id.call_count == 4
    # Verify update_last_login was called twice (existing user)
    assert mock_repository.update_last_login.call_count == 2
    # Results should match
    assert result1.github_id == result2.github_id == 42


def test_default_role_assignment(user_service, mock_repository):
    """Test that new users are created with default role='analyst'."""
    # Create response with role='analyst'
    new_user = UserRecord(
        id="550e8400-e29b-41d4-a716-446655440001",
        github_id=123,
        username="newuser",
        email="new@example.com",
        avatar_url="https://avatars.example.com/newuser",
        role="analyst",
        is_active=True,
        last_login_at=None,
        created_at="2026-04-28T10:00:00Z",
    )

    # Setup: no existing user, create returns new user
    mock_repository.find_by_github_id.return_value = None
    mock_repository.create.return_value = new_user

    result = user_service.get_or_create(
        github_id=123,
        username="newuser",
        email="new@example.com",
        avatar_url="https://avatars.example.com/newuser",
    )

    # Verify create was called once with correct parameters
    mock_repository.create.assert_called_once_with(
        github_id=123,
        username="newuser",
        email="new@example.com",
        avatar_url="https://avatars.example.com/newuser",
    )
    # Verify returned user has role='analyst'
    assert result.role == "analyst"


def test_inactive_user_reactivation(user_service, mock_repository):
    """Test that inactive users are reactivated on login."""
    # Inactive user
    inactive_user = UserRecord(
        id="550e8400-e29b-41d4-a716-446655440002",
        github_id=99,
        username="inactive_user",
        email="inactive@example.com",
        avatar_url="https://avatars.example.com/inactive",
        role="analyst",
        is_active=False,
        last_login_at="2026-01-01T00:00:00Z",
        created_at="2026-01-01T00:00:00Z",
    )

    # Reactivated user (returned after calling reactivate)
    reactivated_user = UserRecord(
        id="550e8400-e29b-41d4-a716-446655440002",
        github_id=99,
        username="inactive_user",
        email="inactive@example.com",
        avatar_url="https://avatars.example.com/inactive",
        role="analyst",
        is_active=True,
        last_login_at="2026-04-28T12:00:00Z",
        created_at="2026-01-01T00:00:00Z",
    )

    # Setup: find returns inactive user, reactivate returns updated user
    mock_repository.find_by_github_id.return_value = inactive_user
    mock_repository.reactivate.return_value = reactivated_user

    result = user_service.get_or_create(
        github_id=99,
        username="inactive_user",
        email="inactive@example.com",
        avatar_url="https://avatars.example.com/inactive",
    )

    # Verify reactivate was called
    mock_repository.reactivate.assert_called_once_with(99)
    # Verify returned user is now active
    assert result.is_active is True


def test_update_last_login_on_existing_active_user(user_service, mock_repository, sample_user_record):
    """Test that existing active users have last_login_at updated."""
    mock_repository.find_by_github_id.return_value = sample_user_record
    mock_repository.update_last_login.return_value = None

    # Call get_or_create for existing active user
    with patch.object(user_service, '_utc_now_iso', return_value="2026-04-28T13:00:00Z"):
        result = user_service.get_or_create(
            github_id=42,
            username="octocat",
            email="octo@example.com",
            avatar_url="https://avatars.example.com/octocat",
        )

    # Verify update_last_login was called
    mock_repository.update_last_login.assert_called_once()
    # Verify reactivate was not called (user already active)
    mock_repository.reactivate.assert_not_called()


def test_email_and_avatar_url_handling_with_none(user_service, mock_repository):
    """Test that None values for email and avatar_url are handled correctly."""
    new_user = UserRecord(
        id="550e8400-e29b-41d4-a716-446655440003",
        github_id=456,
        username="minimal_user",
        email=None,
        avatar_url=None,
        role="analyst",
        is_active=True,
        last_login_at=None,
        created_at="2026-04-28T10:00:00Z",
    )

    mock_repository.find_by_github_id.return_value = None
    mock_repository.create.return_value = new_user

    result = user_service.get_or_create(
        github_id=456,
        username="minimal_user",
        email=None,
        avatar_url=None,
    )

    # Verify create was called with None values
    mock_repository.create.assert_called_once_with(
        github_id=456,
        username="minimal_user",
        email=None,
        avatar_url=None,
    )
    # Verify result has None values preserved
    assert result.email is None
    assert result.avatar_url is None


def test_repository_error_propagation(user_service, mock_repository):
    """Test that repository errors are properly propagated."""
    mock_repository.find_by_github_id.side_effect = UserRepositoryError("Database connection failed")

    with pytest.raises(UserRepositoryError) as exc_info:
        user_service.get_or_create(
            github_id=999,
            username="error_user",
            email=None,
            avatar_url=None,
        )

    assert "Database connection failed" in str(exc_info.value)


def test_enforce_active_status_with_inactive_user(user_service):
    """Test that enforce_active_status raises error for inactive users."""
    inactive_user = UserRecord(
        id="550e8400-e29b-41d4-a716-446655440004",
        github_id=777,
        username="blocked_user",
        email="blocked@example.com",
        avatar_url="https://avatars.example.com/blocked",
        role="analyst",
        is_active=False,
        last_login_at=None,
        created_at="2026-04-28T10:00:00Z",
    )

    with pytest.raises(UserNotFoundError) as exc_info:
        user_service.enforce_active_status(inactive_user)

    assert "inactive" in str(exc_info.value).lower()


def test_enforce_active_status_with_active_user(user_service, sample_user_record):
    """Test that enforce_active_status allows active users."""
    # Should not raise any exception
    user_service.enforce_active_status(sample_user_record)
    # If no exception is raised, test passes
