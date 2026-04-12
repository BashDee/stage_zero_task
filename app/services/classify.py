from typing import Sequence

from httpx import AsyncClient

from app.models.classify import ErrorResponse, SuccessResponse
from app.services.genderize import (
    GenderizeService,
    NoPredictionAvailableError,
    UpstreamServiceError,
)


class ClassifyService:
    def __init__(self, client: AsyncClient):
        self._genderize_service = GenderizeService(client)

    @staticmethod
    def _validate_name(values: Sequence[str]) -> tuple[int, str | ErrorResponse]:
        if not values:
            return 400, ErrorResponse(message="Missing or empty name")

        if len(values) != 1:
            return 422, ErrorResponse(message="name must be a single string")

        name = values[0]
        if not isinstance(name, str):
            return 422, ErrorResponse(message="name must be a string")

        stripped_name = name.strip()
        if stripped_name == "":
            return 400, ErrorResponse(message="Missing or empty name")

        return 200, stripped_name

    async def classify(
        self, values: Sequence[str]
    ) -> tuple[int, SuccessResponse | ErrorResponse]:
        validation_status, validation_result = self._validate_name(values)
        if isinstance(validation_result, ErrorResponse):
            return validation_status, validation_result

        try:
            payload = await self._genderize_service.classify(name=validation_result)
            return 200, payload
        except NoPredictionAvailableError:
            return (
                200,
                ErrorResponse(
                    message="No prediction available for the provided name"
                ),
            )
        except UpstreamServiceError as exc:
            return 502, ErrorResponse(message=str(exc))
