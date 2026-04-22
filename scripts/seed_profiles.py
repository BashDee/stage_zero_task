from __future__ import annotations

import argparse

from app.db import get_supabase_client
from app.services.seed_profiles import load_seed_profiles, seed_profiles


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed 2026 Stage 2 profiles into Supabase")
    parser.add_argument(
        "--file",
        default="data/profiles_2026.json",
        help="Path to the seed JSON file containing unique profiles by name",
    )
    args = parser.parse_args()

    profiles = load_seed_profiles(args.file)
    inserted = seed_profiles(get_supabase_client(), profiles)
    print(f"Seed completed. Inserted {inserted} new rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
