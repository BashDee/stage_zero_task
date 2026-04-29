from __future__ import annotations

import asyncio
import os
import re
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from supabase import create_client

from app.repositories.users import UserRecord
from app.services.seed_profiles import SeedProfile, seed_profiles
from main import app


UUID_V7_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
UTC_ISO_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


@pytest.fixture()
def isolated_client(tmp_path, monkeypatch):
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not supabase_key:
        pytest.skip("Set SUPABASE_URL and SUPABASE_KEY (or SUPABASE_SERVICE_ROLE_KEY) to run integration tests")

    monkeypatch.setenv("SUPABASE_URL", supabase_url)
    monkeypatch.setenv("SUPABASE_KEY", supabase_key)
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-key-stage1")

    with TestClient(app) as client:
        supabase_client = create_client(supabase_url, supabase_key)
        supabase_client.table("profiles").delete().neq("id", "").execute()

        mock_user_repo = Mock()
        mock_user_repo.find_by_github_id.return_value = UserRecord(
            id="550e8400-e29b-41d4-a716-446655440000",
            github_id=42,
            username="octocat",
            email="octo@example.com",
            avatar_url="https://avatars.example.com/octocat",
            role="analyst",
            is_active=True,
            last_login_at=None,
            created_at="2026-04-01T00:00:00Z",
        )
        client.app.state.user_repository = mock_user_repo

        access_token = client.app.state.jwt_service.generate_access_token(
            github_id=42,
            login="octocat",
        )
        client.headers.update({"Authorization": f"Bearer {access_token}"})
        yield client


def install_upstream_successes(client: TestClient, *, gender: str = "female", age: int = 46, country_id: str = "DRC"):
    async def fake_get(url: str, **kwargs):
        await asyncio.sleep(0)
        name = kwargs.get("params", {}).get("name", "unknown")
        if "genderize" in url:
            return FakeResponse({"name": name, "gender": gender, "probability": 0.99, "count": 1234})
        if "agify" in url:
            return FakeResponse({"name": name, "age": age, "count": 999})
        if "nationalize" in url:
            return FakeResponse(
                {
                    "name": name,
                    "country": [
                        {"country_id": country_id, "probability": 0.85},
                        {"country_id": "NG", "probability": 0.2},
                    ],
                }
            )
        raise AssertionError(f"Unexpected URL: {url}")

    client.app.state.http_client.get = fake_get


def install_upstream_custom(client: TestClient, responses_by_service: dict[str, dict]):
    async def fake_get(url: str, **kwargs):
        await asyncio.sleep(0)
        name = kwargs.get("params", {}).get("name", "unknown")
        if "genderize" in url:
            payload = responses_by_service["genderize"]
            return FakeResponse({"name": name, **payload})
        if "agify" in url:
            payload = responses_by_service["agify"]
            return FakeResponse({"name": name, **payload})
        if "nationalize" in url:
            payload = responses_by_service["nationalize"]
            return FakeResponse({"name": name, **payload})
        raise AssertionError(f"Unexpected URL: {url}")

    client.app.state.http_client.get = fake_get


def create_profile(client: TestClient, name: str):
    return client.post("/api/profiles", json={"name": name})


def test_stage0_classify_success(isolated_client):
    async def fake_get(url: str, **kwargs):
        await asyncio.sleep(0)
        return FakeResponse({"gender": "male", "probability": 0.99, "count": 1234})

    isolated_client.app.state.http_client.get = fake_get

    response = isolated_client.get("/api/classify?name=bashir")

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["data"]["name"] == "bashir"
    assert response.json()["data"]["is_confident"] is True


@pytest.mark.parametrize(
    "query, expected_status, expected_message",
    [
        ("/api/classify", 400, "Missing or empty name"),
        ("/api/classify?name=", 400, "Missing or empty name"),
        ("/api/classify?name=a&name=b", 422, "name must be a single string"),
    ],
)
def test_stage0_classify_validation_status_mappings(isolated_client, query, expected_status, expected_message):
    response = isolated_client.get(query)

    assert response.status_code == expected_status
    assert response.json() == {"status": "error", "message": expected_message}


def test_stage0_classify_no_prediction_returns_200_error(isolated_client):
    async def fake_get(url: str, **kwargs):
        await asyncio.sleep(0)
        return FakeResponse({"gender": None, "probability": 0.0, "count": 0})

    isolated_client.app.state.http_client.get = fake_get

    response = isolated_client.get("/api/classify?name=unknown")

    assert response.status_code == 200
    assert response.json() == {
        "status": "error",
        "message": "No prediction available for the provided name",
    }


@pytest.mark.parametrize(
    "body, expected_status, expected_message",
    [
        ({}, 400, "Missing or empty name"),
        ({"name": ""}, 400, "Missing or empty name"),
        ({"name": 123}, 422, "Invalid type"),
        ({"name": ["ella"]}, 422, "Invalid type"),
    ],
)
def test_create_profile_validation_status_mappings(isolated_client, body, expected_status, expected_message):
    response = isolated_client.post("/api/profiles", json=body)

    assert response.status_code == expected_status
    assert response.json() == {"status": "error", "message": expected_message}


def test_create_profile_success_persists_and_returns_contract(isolated_client):
    install_upstream_successes(isolated_client)

    response = create_profile(isolated_client, "ella")

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "success"

    data = payload["data"]
    assert data["name"] == "ella"
    assert data["gender"] == "female"
    assert data["gender_probability"] == pytest.approx(0.99)
    assert data["age"] == 46
    assert data["age_group"] == "adult"
    assert data["country_id"] == "DRC"
    assert isinstance(data["country_name"], str)
    assert data["country_probability"] == pytest.approx(0.85)
    assert UUID_V7_PATTERN.match(data["id"])
    assert UTC_ISO_PATTERN.match(data["created_at"])


def test_duplicate_profile_returns_existing_record(isolated_client):
    install_upstream_successes(isolated_client)

    first_response = create_profile(isolated_client, "ella")
    second_response = create_profile(isolated_client, "Ella")

    assert first_response.status_code == 201
    assert second_response.status_code == 200

    payload = second_response.json()
    assert payload == {
        "status": "success",
        "message": "Profile already exists",
        "data": first_response.json()["data"],
    }


def test_get_single_profile_returns_persisted_record(isolated_client):
    install_upstream_successes(isolated_client)

    created = create_profile(isolated_client, "emmanuel")
    profile_id = created.json()["data"]["id"]

    response = isolated_client.get(f"/api/profiles/{profile_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["data"] == created.json()["data"]


def test_get_single_profile_not_found_returns_404(isolated_client):
    response = isolated_client.get("/api/profiles/00000000-0000-7000-8000-000000000000")

    assert response.status_code == 404
    assert response.json() == {"status": "error", "message": "Profile not found"}


def test_get_profiles_with_combined_filters_returns_and_combined_matches(isolated_client):
    install_upstream_successes(isolated_client, gender="female", age=46, country_id="KE")
    assert create_profile(isolated_client, "ella").status_code == 201

    install_upstream_successes(isolated_client, gender="female", age=31, country_id="KE")
    assert create_profile(isolated_client, "sarah").status_code == 201

    install_upstream_successes(isolated_client, gender="male", age=31, country_id="KE")
    assert create_profile(isolated_client, "john").status_code == 201

    response = isolated_client.get(
        "/api/profiles?gender=female&country_id=ke&age_group=adult"
        "&min_age=40&min_gender_probability=0.9&min_country_probability=0.8"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["page"] == 1
    assert payload["limit"] == 10
    assert payload["total"] == 1
    assert len(payload["data"]) == 1
    assert payload["data"][0]["name"] == "ella"


def test_get_profiles_supports_sorting_and_pagination(isolated_client):
    install_upstream_successes(isolated_client, age=21, gender="male", country_id="AO")
    create_profile(isolated_client, "alpha")
    install_upstream_successes(isolated_client, age=44, gender="female", country_id="AO")
    create_profile(isolated_client, "beta")
    install_upstream_successes(isolated_client, age=33, gender="female", country_id="AO")
    create_profile(isolated_client, "gamma")

    response = isolated_client.get("/api/profiles?sort_by=age&order=desc&page=1&limit=2")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert payload["page"] == 1
    assert payload["limit"] == 2
    assert [row["age"] for row in payload["data"]] == [44, 33]

    page_2 = isolated_client.get("/api/profiles?sort_by=age&order=desc&page=2&limit=2")
    assert page_2.status_code == 200
    assert [row["age"] for row in page_2.json()["data"]] == [21]


@pytest.mark.parametrize(
    "query",
    [
        "/api/profiles?gender=other",
        "/api/profiles?age_group=older",
        "/api/profiles?country_id=KEN",
        "/api/profiles?sort_by=name",
        "/api/profiles?order=descending",
        "/api/profiles?page=0",
        "/api/profiles?limit=60",
        "/api/profiles?min_age=50&max_age=20",
        "/api/profiles?min_gender_probability=2",
        "/api/profiles?unexpected=1",
    ],
)
def test_get_profiles_invalid_query_params_return_422(isolated_client, query):
    response = isolated_client.get(query)
    assert response.status_code == 422
    assert response.json() == {"status": "error", "message": "Invalid query parameters"}


def test_search_profiles_maps_query_into_filters(isolated_client):
    install_upstream_successes(isolated_client, gender="male", age=23, country_id="AO")
    create_profile(isolated_client, "mike")
    install_upstream_successes(isolated_client, gender="female", age=38, country_id="AO")
    create_profile(isolated_client, "ana")

    response = isolated_client.get("/api/profiles/search?q=young%20males%20from%20angola")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["total"] == 1
    assert payload["data"][0]["name"] == "mike"


@pytest.mark.parametrize(
    "query, expected_name",
    [
        ("females above 30", "ana"),
        ("adult males from kenya", "john"),
        ("male and female teenagers above 17", "teen"),
    ],
)
def test_search_profiles_required_mapping_examples(isolated_client, query, expected_name):
    install_upstream_successes(isolated_client, gender="female", age=38, country_id="AO")
    create_profile(isolated_client, "ana")
    install_upstream_successes(isolated_client, gender="male", age=42, country_id="KE")
    create_profile(isolated_client, "john")
    install_upstream_successes(isolated_client, gender="male", age=18, country_id="UG")
    create_profile(isolated_client, "teen")

    response = isolated_client.get(f"/api/profiles/search?q={query.replace(' ', '%20')}")
    assert response.status_code == 200
    names = [row["name"] for row in response.json()["data"]]
    assert expected_name in names


def test_search_profiles_unable_to_interpret_query(isolated_client):
    response = isolated_client.get("/api/profiles/search?q=xyzzyplugh")

    assert response.status_code == 400
    assert response.json() == {"status": "error", "message": "Unable to interpret query"}


def test_search_profiles_missing_q_returns_400(isolated_client):
    response = isolated_client.get("/api/profiles/search")

    assert response.status_code == 400
    assert response.json() == {"status": "error", "message": "Missing or empty required parameter"}


@pytest.mark.parametrize(
    "query",
    [
        "/api/profiles/search?q=young&page=0",
        "/api/profiles/search?q=young&limit=90",
        "/api/profiles/search?q=young&foo=bar",
    ],
)
def test_search_profiles_invalid_query_params_return_422(isolated_client, query):
    response = isolated_client.get(query)
    assert response.status_code == 422
    assert response.json() == {"status": "error", "message": "Invalid query parameters"}


def test_delete_profile_returns_204_and_removes_record(isolated_client):
    install_upstream_successes(isolated_client)

    created = create_profile(isolated_client, "ella")
    profile_id = created.json()["data"]["id"]

    delete_response = isolated_client.delete(f"/api/profiles/{profile_id}")
    assert delete_response.status_code == 204
    assert delete_response.content == b""

    follow_up = isolated_client.get(f"/api/profiles/{profile_id}")
    assert follow_up.status_code == 404


def test_delete_profile_not_found_returns_404(isolated_client):
    response = isolated_client.delete("/api/profiles/00000000-0000-7000-8000-000000000000")

    assert response.status_code == 404
    assert response.json() == {"status": "error", "message": "Profile not found"}


@pytest.mark.parametrize(
    "responses_by_service, expected_message",
    [
        (
            {
                "genderize": {"gender": None, "probability": 0.99, "count": 1234},
                "agify": {"age": 46, "count": 999},
                "nationalize": {"country": [{"country_id": "NG", "probability": 0.2}]},
            },
            "Genderize returned an invalid response",
        ),
        (
            {
                "genderize": {"gender": "female", "probability": 0.99, "count": 1234},
                "agify": {"age": None, "count": 999},
                "nationalize": {"country": [{"country_id": "NG", "probability": 0.2}]},
            },
            "Agify returned an invalid response",
        ),
        (
            {
                "genderize": {"gender": "female", "probability": 0.99, "count": 1234},
                "agify": {"age": 46, "count": 999},
                "nationalize": {"country": []},
            },
            "Nationalize returned an invalid response",
        ),
    ],
)
def test_create_profile_upstream_edge_cases_return_502_and_do_not_persist(
    isolated_client, responses_by_service, expected_message
):
    install_upstream_custom(isolated_client, responses_by_service)

    response = create_profile(isolated_client, "ella")

    assert response.status_code == 502
    assert response.json() == {"status": "error", "message": expected_message}

    get_response = isolated_client.get("/api/profiles")
    assert get_response.status_code == 200
    assert get_response.json()["total"] == 0


class _FakeSelectResult:
    def __init__(self, rows: list[dict]):
        self.data = rows


class _FakeSelectQuery:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def execute(self):
        return _FakeSelectResult(self._rows)


class _FakeInsertQuery:
    def __init__(self, table_ref):
        self._table_ref = table_ref

    def execute(self):
        return _FakeSelectResult([])


class _FakeTable:
    def __init__(self, existing_rows: list[dict]):
        self.existing_rows = existing_rows
        self.inserted_batches: list[list[dict]] = []

    def select(self, *_args, **_kwargs):
        return _FakeSelectQuery(self.existing_rows)

    def insert(self, rows: list[dict]):
        self.inserted_batches.append(rows)
        return _FakeInsertQuery(self)


class _FakeClient:
    def __init__(self, existing_rows: list[dict]):
        self._table = _FakeTable(existing_rows)

    def table(self, _name: str):
        return self._table


def test_seed_profiles_is_idempotent_by_name():
    profiles = [
        SeedProfile(
            name="alice",
            gender="female",
            gender_probability=0.9,
            age=30,
            age_group="adult",
            country_id="AO",
            country_name="Angola",
            country_probability=0.8,
        ),
        SeedProfile(
            name="bob",
            gender="male",
            gender_probability=0.8,
            age=20,
            age_group="adult",
            country_id="KE",
            country_name="Kenya",
            country_probability=0.7,
        ),
    ]
    fake_client = _FakeClient(existing_rows=[{"name": "alice"}])

    inserted = seed_profiles(fake_client, profiles, batch_size=1)

    assert inserted == 1
    assert len(fake_client._table.inserted_batches) == 1
    assert fake_client._table.inserted_batches[0][0]["name"] == "bob"
