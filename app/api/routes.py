from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.models.classify import ErrorResponse, SuccessResponse
from app.services.classify import ClassifyService

router = APIRouter(prefix="/api", tags=["classification"])


def _build_error_response(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(message=message).model_dump(),
    )


@router.get(
    "/classify",
    response_model=SuccessResponse | ErrorResponse,
    summary="Classify a first name using Genderize",
    response_description="Successful classification payload.",
    responses={
        400: {"model": ErrorResponse, "description": "Missing or empty name"},
        422: {"model": ErrorResponse, "description": "Invalid name value"},
        502: {"model": ErrorResponse, "description": "Upstream service failure"},
        500: {"model": ErrorResponse, "description": "Unexpected server error"},
    },
)
async def classify(request: Request):
    values = request.query_params.getlist("name")
    service = ClassifyService(request.app.state.http_client)
    status_code, payload = await service.classify(values)

    if isinstance(payload, ErrorResponse):
        return _build_error_response(status_code, payload.message)

    return payload
