from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.countries import _country_maps


MALE_WORDS = {"male", "males", "man", "men", "boy", "boys"}
FEMALE_WORDS = {"female", "females", "woman", "women", "girl", "girls"}
AGE_GROUP_WORDS = {
    "child": "child",
    "children": "child",
    "teen": "teenager",
    "teens": "teenager",
    "teenager": "teenager",
    "teenagers": "teenager",
    "adult": "adult",
    "adults": "adult",
    "senior": "senior",
    "seniors": "senior",
}


@dataclass(slots=True)
class ParsedSearchFilters:
    gender: str | None = None
    age_group: str | None = None
    country_id: str | None = None
    min_age: int | None = None
    max_age: int | None = None


class ProfileSearchParser:
    @staticmethod
    def _normalize_text(query: str) -> str:
        lowered = query.strip().lower()
        lowered = re.sub(r"[^a-z0-9\s]", " ", lowered)
        return re.sub(r"\s+", " ", lowered).strip()

    @staticmethod
    def _extract_country_id(normalized_query: str) -> str | None:
        aliases, _ = _country_maps()
        # Match longest country phrase first after "from".
        for country_name in sorted(aliases.keys(), key=len, reverse=True):
            if f"from {country_name}" in normalized_query:
                return aliases[country_name]
        return None

    @staticmethod
    def _extract_gender(tokens: list[str]) -> tuple[str | None, bool]:
        has_male = any(token in MALE_WORDS for token in tokens)
        has_female = any(token in FEMALE_WORDS for token in tokens)

        if has_male and has_female:
            return None, True
        if has_male:
            return "male", True
        if has_female:
            return "female", True
        return None, False

    @staticmethod
    def _extract_age_group(tokens: list[str]) -> tuple[str | None, bool]:
        for token in tokens:
            mapped = AGE_GROUP_WORDS.get(token)
            if mapped is not None:
                return mapped, True
        return None, False

    @staticmethod
    def _extract_age_bounds(normalized_query: str) -> tuple[int | None, int | None, bool]:
        min_age = None
        max_age = None
        matched = False

        if "young" in normalized_query.split():
            min_age = 16
            max_age = 24
            matched = True

        min_match = re.search(r"\b(?:above|over|older than|at least)\s+(\d{1,3})\b", normalized_query)
        if min_match:
            min_age = int(min_match.group(1))
            matched = True

        max_match = re.search(r"\b(?:below|under|younger than|at most)\s+(\d{1,3})\b", normalized_query)
        if max_match:
            max_age = int(max_match.group(1))
            matched = True

        return min_age, max_age, matched

    def parse(self, query: str) -> ParsedSearchFilters | None:
        normalized_query = self._normalize_text(query)
        if normalized_query == "":
            return None

        tokens = normalized_query.split()
        matched_any = False

        gender, matched_gender = self._extract_gender(tokens)
        age_group, matched_age_group = self._extract_age_group(tokens)
        country_id = self._extract_country_id(normalized_query)
        if country_id is not None:
            matched_any = True

        min_age, max_age, matched_age = self._extract_age_bounds(normalized_query)
        matched_any = matched_any or matched_gender or matched_age_group or matched_age

        if not matched_any:
            return None

        return ParsedSearchFilters(
            gender=gender,
            age_group=age_group,
            country_id=country_id,
            min_age=min_age,
            max_age=max_age,
        )
