from __future__ import annotations

from functools import lru_cache

# Fallback aliases required by the Stage 2 parser examples and common phrasing.
COUNTRY_ALIASES: dict[str, str] = {
    "angola": "AO",
    "kenya": "KE",
    "congo": "CG",
    "dr congo": "CD",
    "drc": "CD",
    "usa": "US",
    "us": "US",
    "uk": "GB",
    "ivory coast": "CI",
    "south korea": "KR",
    "north korea": "KP",
    "czech republic": "CZ",
    "russia": "RU",
    "tanzania": "TZ",
    "laos": "LA",
    "vietnam": "VN",
    "nigeria": "NG",
}


def _normalize_country_text(value: str) -> str:
    return " ".join(value.strip().lower().replace("-", " ").split())


@lru_cache(maxsize=1)
def _country_maps() -> tuple[dict[str, str], dict[str, str]]:
    aliases = {k: v.upper() for k, v in COUNTRY_ALIASES.items()}
    code_to_name: dict[str, str] = {}

    try:
        import pycountry

        for country in pycountry.countries:
            code = getattr(country, "alpha_2", None)
            if not isinstance(code, str):
                continue
            iso = code.upper()

            primary = getattr(country, "name", iso)
            code_to_name[iso] = str(primary)

            names = {str(primary)}
            official = getattr(country, "official_name", None)
            common = getattr(country, "common_name", None)
            if isinstance(official, str):
                names.add(official)
            if isinstance(common, str):
                names.add(common)

            for name in names:
                aliases[_normalize_country_text(name)] = iso

            aliases[iso.lower()] = iso
    except Exception:
        # Keep deterministic behavior without optional dependency.
        code_to_name.update({"AO": "Angola", "KE": "Kenya", "CD": "Congo (DRC)", "CG": "Congo"})

    return aliases, code_to_name


def country_code_from_name(raw_name: str) -> str | None:
    aliases, _ = _country_maps()
    return aliases.get(_normalize_country_text(raw_name))


def country_name_from_code(country_id: str) -> str:
    _, code_to_name = _country_maps()
    normalized = country_id.strip().upper()
    if normalized in code_to_name:
        return code_to_name[normalized]
    return normalized
