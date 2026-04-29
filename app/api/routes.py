from typing import Any
import math

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.models.classify import ErrorResponse, SuccessResponse
from app.models.profile import PaginationLinks
from app.services.classify import ClassifyService
from app.services.profiles import ProfileNotFoundError, ProfilesService

router = APIRouter(prefix="/api", tags=["classification"])
INVALID_QUERY_PARAMS_MESSAGE = "Invalid query parameters"
PROFILE_API_VERSION_HEADER = "X-API-Version"


def _build_error_response(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(message=message).model_dump(),
    )


def _require_profile_api_version(request: Request) -> JSONResponse | None:
    version = request.headers.get(PROFILE_API_VERSION_HEADER)
    if version is None or version.strip() == "":
        return _build_error_response(400, "API version header required")
    return None


def _single_query_param(request: Request, key: str) -> str | None:
    values = request.query_params.getlist(key)
    if len(values) == 0:
        return None
    if len(values) > 1:
        raise ValueError("duplicate")
    return values[0]


def _parse_positive_int(value: str, *, max_value: int | None = None) -> int:
    parsed = int(value)
    if parsed < 1:
        raise ValueError("range")
    if max_value is not None and parsed > max_value:
        raise ValueError("range")
    return parsed


def _parse_non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise ValueError("range")
    return parsed


def _parse_probability(value: str) -> float:
    parsed = float(value)
    if parsed < 0.0 or parsed > 1.0:
        raise ValueError("range")
    return parsed


def _build_pagination_links(
    request: Request,
    page: int,
    limit: int,
    total: int,
    endpoint: str,
) -> PaginationLinks:
    """Build pagination links (self, next, prev) for a paginated response.
    
    Args:
        request: FastAPI request object with query params
        page: Current page number (1-indexed)
        limit: Items per page
        total: Total number of items
        endpoint: API endpoint path (e.g., '/profiles' or '/profiles/search')
    """
    total_pages = math.ceil(total / limit) if total > 0 else 0
    
    # Build self link with all current query params
    query_params_list = []
    for key, value in request.query_params.items():
        query_params_list.append(f"{key}={value}")
    self_url = endpoint
    if query_params_list:
        self_url = f"{endpoint}?{'&'.join(query_params_list)}"
    
    # Build next link if not on last page
    next_url = None
    if page < total_pages:
        # Reconstruct URL with next page
        params = dict(request.query_params)
        params['page'] = str(page + 1)
        query_parts = [f"{k}={v}" for k, v in params.items()]
        next_url = f"{endpoint}?{'&'.join(query_parts)}"
    
    # Build prev link if not on first page
    prev_url = None
    if page > 1:
        # Reconstruct URL with previous page
        params = dict(request.query_params)
        params['page'] = str(page - 1)
        query_parts = [f"{k}={v}" for k, v in params.items()]
        prev_url = f"{endpoint}?{'&'.join(query_parts)}"
    
    return PaginationLinks(self=self_url, next=next_url, prev=prev_url)


def _parse_probability(value: str) -> float:
    parsed = float(value)
    if parsed < 0.0 or parsed > 1.0:
        raise ValueError("range")
    return parsed


def _parse_profiles_list_query(request: Request) -> dict[str, Any]:
    allowed = {
        "format",
        "gender",
        "age_group",
        "country_id",
        "min_age",
        "max_age",
        "min_gender_probability",
        "min_country_probability",
        "sort_by",
        "order",
        "page",
        "limit",
    }

    for key in request.query_params.keys():
        if key not in allowed:
            raise ValueError("invalid")

    gender = _single_query_param(request, "gender")
    age_group = _single_query_param(request, "age_group")
    country_id = _single_query_param(request, "country_id")
    min_age = _single_query_param(request, "min_age")
    max_age = _single_query_param(request, "max_age")
    min_gender_probability = _single_query_param(request, "min_gender_probability")
    min_country_probability = _single_query_param(request, "min_country_probability")
    sort_by = (_single_query_param(request, "sort_by") or "created_at").strip().lower()
    order = (_single_query_param(request, "order") or "asc").strip().lower()
    page = _single_query_param(request, "page") or "1"
    limit = _single_query_param(request, "limit") or "10"

    if gender is not None and gender.strip().lower() not in {"male", "female"}:
        raise ValueError("invalid")

    if age_group is not None and age_group.strip().lower() not in {
        "child",
        "teenager",
        "adult",
        "senior",
    }:
        raise ValueError("invalid")

    if country_id is not None:
        cleaned_country_id = country_id.strip().upper()
        if len(cleaned_country_id) != 2 or not cleaned_country_id.isalpha():
            raise ValueError("invalid")

    if sort_by not in {"age", "created_at", "gender_probability"}:
        raise ValueError("invalid")

    if order not in {"asc", "desc"}:
        raise ValueError("invalid")

    parsed_min_age = _parse_non_negative_int(min_age) if min_age is not None else None
    parsed_max_age = _parse_non_negative_int(max_age) if max_age is not None else None

    if (
        parsed_min_age is not None
        and parsed_max_age is not None
        and parsed_min_age > parsed_max_age
    ):
        raise ValueError("invalid")

    return {
        "gender": gender,
        "age_group": age_group,
        "country_id": country_id,
        "min_age": parsed_min_age,
        "max_age": parsed_max_age,
        "min_gender_probability": _parse_probability(min_gender_probability)
        if min_gender_probability is not None
        else None,
        "min_country_probability": _parse_probability(min_country_probability)
        if min_country_probability is not None
        else None,
        "sort_by": sort_by,
        "order": order,
        "page": _parse_positive_int(page),
        "limit": _parse_positive_int(limit, max_value=50),
    }


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


@router.post(
    "/profiles",
    summary="Create profile for a name",
    responses={
        200: {"description": "Profile already exists"},
        201: {"description": "Profile created"},
        400: {
            "model": ErrorResponse,
            "description": "API version header required or missing/empty name",
        },
        422: {"model": ErrorResponse, "description": "Invalid type"},
        502: {"model": ErrorResponse, "description": "Upstream service failure"},
        500: {"model": ErrorResponse, "description": "Unexpected server error"},
    },
)
async def create_profile(request: Request):
    version_error = _require_profile_api_version(request)
    if version_error is not None:
        return version_error

    try:
        body = await request.json()
    except Exception:
        body = {}

    if not isinstance(body, dict):
        return _build_error_response(422, "Invalid type")

    service = ProfilesService(request.app.state.http_client)
    status_code, payload = await service.create_profile(body.get("name"))
    if isinstance(payload, ErrorResponse):
        return _build_error_response(status_code, payload.message)

    return JSONResponse(status_code=status_code, content=payload.model_dump())


@router.get(
    "/profiles/search",
    summary="Search profiles with natural language",
    responses={
        200: {"description": "Profiles fetched"},
        400: {
            "model": ErrorResponse,
            "description": "API version header required or missing/invalid query",
        },
        422: {"model": ErrorResponse, "description": "Invalid query parameters"},
        500: {"model": ErrorResponse, "description": "Unexpected server error"},
    },
)
async def search_profiles(request: Request):
    version_error = _require_profile_api_version(request)
    if version_error is not None:
        return version_error

    for key in request.query_params.keys():
        if key not in {"q", "page", "limit"}:
            return _build_error_response(422, INVALID_QUERY_PARAMS_MESSAGE)

    try:
        page = _single_query_param(request, "page") or "1"
        limit = _single_query_param(request, "limit") or "10"
        q = _single_query_param(request, "q")
    except ValueError:
        return _build_error_response(422, INVALID_QUERY_PARAMS_MESSAGE)

    if q is None or q.strip() == "":
        return _build_error_response(400, "Missing or empty required parameter")

    # Reuse numeric validation for pagination.
    try:
        page_value = _parse_positive_int(page)
        limit_value = _parse_positive_int(limit, max_value=50)
    except (ValueError, TypeError):
        return _build_error_response(422, INVALID_QUERY_PARAMS_MESSAGE)

    service = ProfilesService(request.app.state.http_client)
    
    # First call service with temporary links, then rebuild with actual total
    temp_links = PaginationLinks(self=str(request.url), next=None, prev=None)
    payload = service.search_profiles(query=q, page=page_value, limit=limit_value, links=temp_links)
    if payload is None:
        return _build_error_response(400, "Unable to interpret query")
    
    # Rebuild links with actual total from the response
    actual_links = _build_pagination_links(request, page_value, limit_value, payload.total, "/api/profiles/search")
    payload.links = actual_links
    
    return payload


@router.get(
    "/profiles/export",
    summary="Export profiles as CSV",
    responses={
        200: {"description": "CSV file exported"},
        400: {"model": ErrorResponse, "description": "API version header required"},
        422: {"model": ErrorResponse, "description": "Invalid query parameters"},
        500: {"model": ErrorResponse, "description": "Unexpected server error"},
    },
)
async def export_profiles(request: Request):
    version_error = _require_profile_api_version(request)
    if version_error is not None:
        return version_error

    # Validate format parameter
    try:
        format_value = _single_query_param(request, "format")
    except ValueError:
        return _build_error_response(422, INVALID_QUERY_PARAMS_MESSAGE)
    
    if format_value is None:
        return _build_error_response(422, INVALID_QUERY_PARAMS_MESSAGE)
    
    if format_value.strip().lower() != "csv":
        return _build_error_response(422, INVALID_QUERY_PARAMS_MESSAGE)

    # Parse filtering and sorting parameters (ignore page/limit)
    try:
        query = _parse_profiles_list_query(request)
    except (ValueError, TypeError):
        return _build_error_response(422, INVALID_QUERY_PARAMS_MESSAGE)

    service = ProfilesService(request.app.state.http_client)
    csv_content, timestamp = service.export_profiles_csv(
        gender=query["gender"],
        country_id=query["country_id"],
        age_group=query["age_group"],
        min_age=query["min_age"],
        max_age=query["max_age"],
        min_gender_probability=query["min_gender_probability"],
        min_country_probability=query["min_country_probability"],
        sort_by=query["sort_by"],
        order=query["order"],
    )
    
    # Return CSV as streaming response
    filename = f"profiles_{timestamp}.csv"
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/profiles/{profile_id}",
    summary="Get profile by ID",
    responses={
        200: {"description": "Profile found"},
        400: {"model": ErrorResponse, "description": "API version header required"},
        404: {"model": ErrorResponse, "description": "Profile not found"},
        500: {"model": ErrorResponse, "description": "Unexpected server error"},
    },
)
async def get_profile(profile_id: str, request: Request):
    version_error = _require_profile_api_version(request)
    if version_error is not None:
        return version_error

    service = ProfilesService(request.app.state.http_client)
    try:
        payload = service.get_profile(profile_id)
    except ProfileNotFoundError:
        return _build_error_response(404, "Profile not found")

    return payload


@router.get(
    "/profiles",
    summary="Get all profiles",
    responses={
        200: {"description": "Profiles fetched"},
        400: {"model": ErrorResponse, "description": "API version header required"},
        500: {"model": ErrorResponse, "description": "Unexpected server error"},
    },
)
async def get_profiles(
    request: Request,
):
    version_error = _require_profile_api_version(request)
    if version_error is not None:
        return version_error

    try:
        query = _parse_profiles_list_query(request)
    except (ValueError, TypeError):
        return _build_error_response(422, INVALID_QUERY_PARAMS_MESSAGE)

    service = ProfilesService(request.app.state.http_client)
    page = query["page"]
    limit = query["limit"]
    
    # First call service with temporary links, then rebuild with actual total
    temp_links = PaginationLinks(self=str(request.url), next=None, prev=None)
    result = service.list_profiles(**{**query, "links": temp_links})
    
    # Now rebuild links with actual total from the response
    actual_links = _build_pagination_links(request, page, limit, result.total, "/api/profiles")
    result.links = actual_links
    
    return result


@router.delete(
    "/profiles/{profile_id}",
    status_code=204,
    summary="Delete profile by ID",
    responses={
        204: {"description": "Profile deleted"},
        400: {"model": ErrorResponse, "description": "API version header required"},
        404: {"model": ErrorResponse, "description": "Profile not found"},
        500: {"model": ErrorResponse, "description": "Unexpected server error"},
    },
)
async def delete_profile(profile_id: str, request: Request):
    version_error = _require_profile_api_version(request)
    if version_error is not None:
        return version_error

    service = ProfilesService(request.app.state.http_client)
    deleted = service.delete_profile(profile_id)
    if not deleted:
        return _build_error_response(404, "Profile not found")
    return Response(status_code=204)
