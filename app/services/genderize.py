from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from httpx import AsyncClient, HTTPError

from app.models.classify import ClassifyData, SuccessResponse


GENDERIZE_URL = "https://api.genderize.io"


class NoPredictionAvailableError(Exception):
    pass


class UpstreamServiceError(Exception):
    pass


@dataclass(slots=True)
class GenderizePayload:
    gender: str | None
    probability: float
    sample_size: int


class GenderizeService:
    def __init__(self, client: AsyncClient):
        self._client = client

    @staticmethod
    def _processed_at() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )

    @staticmethod
    def _build_payload(name: str, response: GenderizePayload) -> SuccessResponse:
        is_confident = response.probability >= 0.7 and response.sample_size >= 100
        return SuccessResponse(
            data=ClassifyData(
                name=name,
                gender=response.gender,
                probability=response.probability,
                sample_size=response.sample_size,
                is_confident=is_confident,
                processed_at=GenderizeService._processed_at(),
            )
        )

    async def classify(self, name: str) -> SuccessResponse:
        try:
            response = await self._client.get(
                GENDERIZE_URL,
                params={"name": name},
            )
            response.raise_for_status()
            body = response.json()
        except (HTTPError, ValueError, TypeError) as exc:
            raise UpstreamServiceError("Failed to reach Genderize API") from exc

        if not isinstance(body, dict):
            raise UpstreamServiceError("Genderize API returned an invalid payload")

        gender = body.get("gender")
        count = body.get("count")

        if gender is None:
            raise NoPredictionAvailableError()

        if count is None:
            raise UpstreamServiceError("Genderize API returned an incomplete payload")

        if count == 0:
            raise NoPredictionAvailableError()

        probability = body.get("probability")
        if probability is None:
            raise UpstreamServiceError("Genderize API returned an incomplete payload")

        try:
            probability_value = float(probability)
            sample_size = int(count)
        except (TypeError, ValueError) as exc:
            raise UpstreamServiceError("Genderize API returned an invalid payload") from exc

        return self._build_payload(
            name=name,
            response=GenderizePayload(
                gender=gender,
                probability=probability_value,
                sample_size=sample_size,
            ),
        )
