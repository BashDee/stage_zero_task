from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from supabase import Client


PROFILE_SELECT_FIELDS = (
    "id,name,gender,gender_probability,age,age_group,country_id,country_name,country_probability,created_at"
)
PROFILE_SELECT_FIELDS_FALLBACK = (
    "id,name,gender,gender_probability,age,age_group,country_id,country_probability,created_at"
)


@dataclass(slots=True)
class ProfileRecord:
    id: str
    name: str
    gender: str
    gender_probability: float
    age: int
    age_group: str
    country_id: str
    country_name: str
    country_probability: float
    created_at: str


@dataclass(slots=True)
class NewProfileRecord:
    id: str
    name: str
    gender: str
    gender_probability: float
    sample_size: int | None
    age: int
    age_group: str
    country_id: str
    country_name: str
    country_probability: float
    created_at: str


@dataclass(slots=True)
class ProfileQuery:
    gender: str | None = None
    age_group: str | None = None
    country_id: str | None = None
    min_age: int | None = None
    max_age: int | None = None
    min_gender_probability: float | None = None
    min_country_probability: float | None = None
    sort_by: Literal["age", "created_at", "gender_probability"] = "created_at"
    order: Literal["asc", "desc"] = "asc"
    page: int = 1
    limit: int = 10


@dataclass(slots=True)
class ProfileQueryResult:
    rows: list[ProfileRecord]
    total: int


class ProfileRepository:
    def __init__(self, client: Client):
        self._client = client
        self._has_country_name = self._detect_country_name_column()
        self._has_normalized_name = self._detect_column("normalized_name")
        self._has_normalized_gender = self._detect_column("normalized_gender")
        self._has_normalized_age_group = self._detect_column("normalized_age_group")
        self._has_normalized_country_id = self._detect_column("normalized_country_id")
        self._has_sample_size = self._detect_column("sample_size")

    def _detect_country_name_column(self) -> bool:
        return self._detect_column("country_name")

    def _detect_column(self, name: str) -> bool:
        try:
            self._client.table("profiles").select(name).limit(1).execute()
            return True
        except Exception:
            return False

    def _select_fields(self) -> str:
        if self._has_country_name:
            return PROFILE_SELECT_FIELDS
        return PROFILE_SELECT_FIELDS_FALLBACK

    @staticmethod
    def _map_row(row: dict) -> ProfileRecord:
        return ProfileRecord(
            id=row["id"],
            name=row["name"],
            gender=row["gender"],
            gender_probability=row["gender_probability"],
            age=row["age"],
            age_group=row["age_group"],
            country_id=row["country_id"],
            country_name=row.get("country_name") or row["country_id"],
            country_probability=row["country_probability"],
            created_at=row["created_at"],
        )

    def get_by_name(self, normalized_name: str) -> ProfileRecord | None:
        response = (
            self._client.table("profiles")
            .select(self._select_fields())
            .eq("name", normalized_name)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        row = rows[0] if rows else None

        if row is None:
            return None
        return self._map_row(row)

    def get_by_id(self, profile_id: str) -> ProfileRecord | None:
        response = (
            self._client.table("profiles")
            .select(self._select_fields())
            .eq("id", profile_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        row = rows[0] if rows else None

        if row is None:
            return None
        return self._map_row(row)

    def create(self, record: NewProfileRecord) -> ProfileRecord:
        insert_payload = {
            "id": record.id,
            "name": record.name,
            "gender": record.gender,
            "gender_probability": record.gender_probability,
            "age": record.age,
            "age_group": record.age_group,
            "country_id": record.country_id,
            "country_probability": record.country_probability,
            "created_at": record.created_at,
        }
        if self._has_country_name:
            insert_payload["country_name"] = record.country_name
        if self._has_sample_size and record.sample_size is not None:
            insert_payload["sample_size"] = record.sample_size
        if self._has_normalized_name:
            insert_payload["normalized_name"] = record.name.strip().lower()
        if self._has_normalized_gender:
            insert_payload["normalized_gender"] = record.gender.strip().lower()
        if self._has_normalized_age_group:
            insert_payload["normalized_age_group"] = record.age_group.strip().lower()
        if self._has_normalized_country_id:
            insert_payload["normalized_country_id"] = record.country_id.strip().lower()

        self._client.table("profiles").insert(insert_payload).execute()

        return ProfileRecord(
            id=record.id,
            name=record.name,
            gender=record.gender,
            gender_probability=record.gender_probability,
            age=record.age,
            age_group=record.age_group,
            country_id=record.country_id,
            country_name=record.country_name,
            country_probability=record.country_probability,
            created_at=record.created_at,
        )

    def list_profiles(self, query_spec: ProfileQuery) -> ProfileQueryResult:
        query = self._client.table("profiles").select(self._select_fields(), count="exact")

        if query_spec.gender is not None:
            query = query.eq("gender", query_spec.gender)

        if query_spec.age_group is not None:
            query = query.eq("age_group", query_spec.age_group)

        if query_spec.country_id is not None:
            query = query.eq("country_id", query_spec.country_id)

        if query_spec.min_age is not None:
            query = query.gte("age", query_spec.min_age)

        if query_spec.max_age is not None:
            query = query.lte("age", query_spec.max_age)

        if query_spec.min_gender_probability is not None:
            query = query.gte("gender_probability", query_spec.min_gender_probability)

        if query_spec.min_country_probability is not None:
            query = query.gte("country_probability", query_spec.min_country_probability)

        start = (query_spec.page - 1) * query_spec.limit
        end = start + query_spec.limit - 1
        response = (
            query.order(query_spec.sort_by, desc=(query_spec.order == "desc"))
            .range(start, end)
            .execute()
        )
        rows = response.data or []

        return ProfileQueryResult(
            rows=[self._map_row(row) for row in rows],
            total=int(response.count or 0),
        )

    def list_profiles_unbounded(self, query_spec: ProfileQuery) -> list[ProfileRecord]:
        """List all profiles matching filters without pagination.
        
        Args:
            query_spec: Filter and sort specification (page/limit fields are ignored)
        
        Returns:
            List of all matching ProfileRecord objects
        """
        query = self._client.table("profiles").select(self._select_fields())

        if query_spec.gender is not None:
            query = query.eq("gender", query_spec.gender)

        if query_spec.age_group is not None:
            query = query.eq("age_group", query_spec.age_group)

        if query_spec.country_id is not None:
            query = query.eq("country_id", query_spec.country_id)

        if query_spec.min_age is not None:
            query = query.gte("age", query_spec.min_age)

        if query_spec.max_age is not None:
            query = query.lte("age", query_spec.max_age)

        if query_spec.min_gender_probability is not None:
            query = query.gte("gender_probability", query_spec.min_gender_probability)

        if query_spec.min_country_probability is not None:
            query = query.gte("country_probability", query_spec.min_country_probability)

        response = (
            query.order(query_spec.sort_by, desc=(query_spec.order == "desc"))
            .execute()
        )
        rows = response.data or []

        return [self._map_row(row) for row in rows]

    def delete(self, profile_id: str) -> bool:
        # Check if record exists
        existing = self.get_by_id(profile_id)
        if existing is None:
            return False
        
        # Delete it
        self._client.table("profiles").delete().eq("id", profile_id).execute()
        return True
