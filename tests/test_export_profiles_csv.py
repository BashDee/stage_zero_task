from __future__ import annotations

import os
import re
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from supabase import create_client

from app.repositories.users import UserRecord
from app.services.seed_profiles import load_seed_profiles, seed_profiles
from main import app


@pytest.fixture()
def client_with_auth(tmp_path, monkeypatch):
    """Create a test client with authentication and seeded profiles."""
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not supabase_key:
        pytest.skip("Set SUPABASE_URL and SUPABASE_KEY (or SUPABASE_SERVICE_ROLE_KEY) to run integration tests")

    monkeypatch.setenv("SUPABASE_URL", supabase_url)
    monkeypatch.setenv("SUPABASE_KEY", supabase_key)
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-key-export")

    with TestClient(app) as client:
        supabase_client = create_client(supabase_url, supabase_key)
        # Clean up profiles table - use gt comparison with UUID min value to avoid empty string cast error
        try:
            supabase_client.table("profiles").delete().gt("id", "00000000-0000-0000-0000-000000000000").execute()
        except Exception:
            pass  # Ignore cleanup errors
        
        # Seed test profiles
        seed_file = Path(__file__).parent.parent / "seed_profiles.json"
        profiles = load_seed_profiles(seed_file)
        seed_profiles(supabase_client, profiles)

        # Mock user repository
        mock_user_repo = Mock()
        mock_user_repo.find_by_github_id.return_value = UserRecord(
            id="550e8400-e29b-41d4-a716-446655440000",
            github_id=42,
            username="testuser",
            email="test@example.com",
            avatar_url="https://avatars.example.com/test",
            role="analyst",
            is_active=True,
            last_login_at=None,
            created_at="2026-04-01T00:00:00Z",
        )
        client.app.state.user_repository = mock_user_repo

        # Generate and set access token
        access_token = client.app.state.jwt_service.generate_access_token(
            github_id=42,
            login="testuser",
        )
        client.headers.update(
            {
                "Authorization": f"Bearer {access_token}",
                "X-API-Version": "1.0",
            }
        )
        yield client
        
        # Cleanup
        try:
            supabase_client.table("profiles").delete().gt("id", "00000000-0000-0000-0000-000000000000").execute()
        except Exception:
            pass


class TestExportProfilesCSV:
    def test_export_all_profiles_as_csv(self, client_with_auth):
        """Test exporting all profiles without filters."""
        response = client_with_auth.get("/api/profiles/export?format=csv")
        
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv"
        assert "attachment" in response.headers.get("content-disposition", "")
        assert "profiles_" in response.headers.get("content-disposition", "")
        assert ".csv" in response.headers.get("content-disposition", "")
        
        # Verify CSV structure
        lines = response.text.strip().split("\n")
        assert len(lines) > 1, "CSV should have at least header and one data row"
        
        # Check header
        header = lines[0]
        expected_header = "id,name,gender,gender_probability,age,age_group,country_id,country_name,country_probability,created_at"
        assert header == expected_header
        
        # Check data rows have correct number of fields
        for line in lines[1:]:
            fields = line.split(",")
            assert len(fields) == 10, f"Each row should have 10 fields, got {len(fields)}"

    def test_export_csv_with_gender_filter(self, client_with_auth):
        """Test exporting profiles filtered by gender."""
        response = client_with_auth.get("/api/profiles/export?format=csv&gender=male")
        
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv"
        
        # Check that all data rows have gender=male
        lines = response.text.strip().split("\n")
        header_fields = lines[0].split(",")
        gender_index = header_fields.index("gender")
        
        for line in lines[1:]:
            fields = line.split(",")
            assert fields[gender_index].lower() == "male"

    def test_export_csv_with_age_range_filter(self, client_with_auth):
        """Test exporting profiles filtered by age range."""
        response = client_with_auth.get("/api/profiles/export?format=csv&min_age=20&max_age=40")
        
        assert response.status_code == 200
        
        lines = response.text.strip().split("\n")
        header_fields = lines[0].split(",")
        age_index = header_fields.index("age")
        
        for line in lines[1:]:
            fields = line.split(",")
            age = int(fields[age_index])
            assert 20 <= age <= 40

    def test_export_csv_with_sorting(self, client_with_auth):
        """Test exporting profiles with custom sorting."""
        response = client_with_auth.get("/api/profiles/export?format=csv&sort_by=age&order=desc")
        
        assert response.status_code == 200
        
        lines = response.text.strip().split("\n")
        header_fields = lines[0].split(",")
        age_index = header_fields.index("age")
        
        # Extract ages from data rows
        ages = []
        for line in lines[1:]:
            fields = line.split(",")
            ages.append(int(fields[age_index]))
        
        # Verify they are sorted in descending order
        assert ages == sorted(ages, reverse=True)

    def test_export_csv_missing_format_param(self, client_with_auth):
        """Test that missing format parameter returns 422."""
        response = client_with_auth.get("/api/profiles/export")
        
        assert response.status_code == 422
        assert "Invalid query parameters" in response.text

    def test_export_csv_invalid_format(self, client_with_auth):
        """Test that invalid format value returns 422."""
        response = client_with_auth.get("/api/profiles/export?format=json")
        
        assert response.status_code == 422
        assert "Invalid query parameters" in response.text

    def test_export_csv_missing_api_version_header(self, client_with_auth):
        """Test that missing X-API-Version header returns 400."""
        client_with_auth.headers.pop("X-API-Version")
        response = client_with_auth.get("/api/profiles/export?format=csv")
        
        assert response.status_code == 400
        assert "API version header required" in response.text

    def test_export_csv_with_invalid_query_params(self, client_with_auth):
        """Test that invalid query parameters return 422."""
        response = client_with_auth.get("/api/profiles/export?format=csv&gender=invalid")
        
        assert response.status_code == 422

    def test_export_csv_empty_result(self, client_with_auth):
        """Test exporting with filters that match no profiles."""
        response = client_with_auth.get("/api/profiles/export?format=csv&age_group=nonexistent")
        
        assert response.status_code == 200
        
        lines = response.text.strip().split("\n")
        # Should only have header row
        assert len(lines) == 1
        
        header = lines[0]
        expected_header = "id,name,gender,gender_probability,age,age_group,country_id,country_name,country_probability,created_at"
        assert header == expected_header

    def test_export_csv_filename_format(self, client_with_auth):
        """Test that filename has correct format with timestamp."""
        response = client_with_auth.get("/api/profiles/export?format=csv")
        
        disposition = response.headers.get("content-disposition", "")
        # Check filename matches pattern: profiles_YYYY-MM-DDTHH_MM_SSZ.csv
        assert re.search(r'profiles_\d{4}-\d{2}-\d{2}T\d{2}_\d{2}_\d{2}Z\.csv', disposition)
