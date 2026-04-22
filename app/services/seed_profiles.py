from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
import os
import time
from pathlib import Path
from uuid import UUID

from supabase import Client

from app.services.countries import country_name_from_code


@dataclass(slots=True)
class SeedProfile:
    name: str
    gender: str
    gender_probability: float
    age: int
    age_group: str
    country_id: str
    country_name: str
    country_probability: float


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _uuid_v7() -> str:
    unix_ms = int(time.time() * 1000)
    random_bytes = bytearray(os.urandom(10))
    raw = bytearray(16)

    raw[0:6] = unix_ms.to_bytes(6, byteorder="big", signed=False)
    raw[6] = 0x70 | (random_bytes[0] & 0x0F)
    raw[7] = random_bytes[1]
    raw[8] = 0x80 | (random_bytes[2] & 0x3F)
    raw[9:16] = random_bytes[3:10]

    return str(UUID(bytes=bytes(raw)))


def _age_group(age: int) -> str:
    if age <= 12:
        return "child"
    if age <= 19:
        return "teenager"
    if age <= 59:
        return "adult"
    return "senior"


def _to_seed_profile(raw: dict) -> SeedProfile:
    name = str(raw.get("name", "")).strip().lower()
    if name == "":
        raise ValueError("seed profile name is required")

    gender = str(raw.get("gender", "")).strip().lower()
    if gender not in {"male", "female"}:
        raise ValueError(f"invalid gender for {name}")

    age = int(raw.get("age"))
    if age < 0:
        raise ValueError(f"invalid age for {name}")

    country_id = str(raw.get("country_id", "")).strip().upper()
    if len(country_id) != 2 or not country_id.isalpha():
        raise ValueError(f"invalid country_id for {name}")

    country_name = str(raw.get("country_name", "")).strip() or country_name_from_code(country_id)

    gender_probability = float(raw.get("gender_probability", 0.0))
    country_probability = float(raw.get("country_probability", 0.0))
    if not (0.0 <= gender_probability <= 1.0):
        raise ValueError(f"invalid gender_probability for {name}")
    if not (0.0 <= country_probability <= 1.0):
        raise ValueError(f"invalid country_probability for {name}")

    age_group = str(raw.get("age_group", "")).strip().lower() or _age_group(age)
    if age_group not in {"child", "teenager", "adult", "senior"}:
        raise ValueError(f"invalid age_group for {name}")

    return SeedProfile(
        name=name,
        gender=gender,
        gender_probability=gender_probability,
        age=age,
        age_group=age_group,
        country_id=country_id,
        country_name=country_name,
        country_probability=country_probability,
    )


def load_seed_profiles(path: str | Path) -> list[SeedProfile]:
    seed_path = Path(path)
    rows = json.loads(seed_path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("seed file must contain a JSON array")

    parsed = [_to_seed_profile(row) for row in rows]
    deduped: dict[str, SeedProfile] = {}
    for item in parsed:
        deduped[item.name] = item

    unique_profiles = list(deduped.values())
    if len(unique_profiles) != 2026:
        raise ValueError("seed file must contain exactly 2026 unique profiles by name")

    return unique_profiles


def seed_profiles(client: Client, profiles: list[SeedProfile], batch_size: int = 500) -> int:
    existing_response = client.table("profiles").select("name").execute()
    existing_rows = existing_response.data or []
    existing_names = {str(row["name"]).strip().lower() for row in existing_rows if "name" in row}

    to_insert = []
    timestamp = _utc_now_iso()
    for profile in profiles:
        if profile.name in existing_names:
            continue
        to_insert.append(
            {
                "id": _uuid_v7(),
                "name": profile.name,
                "gender": profile.gender,
                "gender_probability": profile.gender_probability,
                "age": profile.age,
                "age_group": profile.age_group,
                "country_id": profile.country_id,
                "country_name": profile.country_name,
                "country_probability": profile.country_probability,
                "created_at": timestamp,
            }
        )

    inserted = 0
    for start in range(0, len(to_insert), batch_size):
        batch = to_insert[start : start + batch_size]
        if not batch:
            continue
        client.table("profiles").insert(batch).execute()
        inserted += len(batch)

    return inserted
