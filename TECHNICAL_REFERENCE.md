# Technical Reference

## 1. Project Summary

This project is a FastAPI service that provides two API stages:

- Stage 0 classification (`GET /api/classify`) using Genderize.
- Stage 1 profile persistence (`POST/GET/DELETE /api/profiles`) using Genderize, Agify, Nationalize, and Supabase Postgres.
- Stage 2 GitHub OAuth PKCE identity exchange (`GET /auth/github`, `GET /auth/github/callback`) without local session issuance.

The service standardizes successful and error responses, performs strict request validation, and persists normalized profile fields for deterministic filtering and idempotent profile creation.

## 2. Technology Stack

- Python 3.13
- FastAPI
- httpx (shared async HTTP client)
- Pydantic models for contracts
- Supabase Python client (Postgres access)
- Uvicorn
- pytest + FastAPI TestClient
- Docker / docker-compose / Render deployment manifest

## 3. Runtime Architecture

### 3.1 App bootstrap

`main.py` configures:

- FastAPI metadata (title/version/description)
- Lifecycle management (`lifespan`) for one shared `httpx.AsyncClient`
- Startup DB accessibility check via `init_db()`
- CORS with wildcard origin support
- Global exception handlers returning a unified error envelope
- Route registration from `app/api/routes.py`

### 3.2 Layered responsibilities

- `app/api/routes.py`: HTTP boundary, request parsing, status-code wiring.
- `app/api/auth.py`: GitHub OAuth route boundary, redirect handling, callback validation, and identity payload shaping.
- `app/services/*.py`: business logic, validation, upstream orchestration.
- `app/repositories/profiles.py`: persistence logic against Supabase `profiles` table.

### 3.3 GitHub OAuth PKCE flow

- `app/services/github_oauth.py` owns the PKCE pair generation, GitHub authorization URL construction, token exchange, and user profile normalization.
- A short-lived in-memory state store protects the callback verifier and enforces one-time use without introducing a database dependency.
- The callback route validates `state` before exchanging the `code`, and GitHub token exchange or user lookup failures are translated into predictable API errors.
- The module intentionally stops at GitHub identity exchange and does not mint local JWTs, cookies, or refresh tokens.

### 3.4 GitHub OAuth configuration

- `GITHUB_CLIENT_ID` is required.
- `GITHUB_CLIENT_SECRET` is optional.
- `GITHUB_OAUTH_SCOPE` defaults to `read:user user:email`.
- `app/models/*.py`: response and data contracts.
- `app/db.py`: environment-driven Supabase client creation and startup health check.

### 3.3 Upstream integrations

- Genderize: `https://api.genderize.io`
- Agify: `https://api.agify.io`
- Nationalize: `https://api.nationalize.io`

All integrations convert transport/parsing failures into service-level errors.

## 4. API Surface

Base path: `/api`

### 4.1 Stage 0 endpoint

#### GET /api/classify

Query:

- `name` (required, single value)

Behavior:

- Validates query shape and contents.
- Calls Genderize.
- Computes confidence as:

$$
\text{is\_confident} = (\text{probability} \ge 0.7) \land (\text{sample\_size} \ge 100)
$$

Success envelope:

```json
{
  "status": "success",
  "data": {
    "name": "bashir",
    "gender": "male",
    "probability": 0.99,
    "sample_size": 1234,
    "is_confident": true,
    "processed_at": "2026-04-01T12:00:00Z"
  }
}
```

Primary status mappings:

- `200`: successful classification
- `200`: no-prediction case (`status: error`, message indicates no prediction)
- `400`: missing/empty `name`
- `422`: invalid `name` shape (for example, repeated query values)
- `502`: upstream service failure

### 4.2 Stage 1 endpoints

#### POST /api/profiles

Request body:

```json
{ "name": "ella" }
```

Behavior:

- Validates name.
- Normalizes name (`strip().lower()`) for idempotency.
- Returns existing record when normalized name already exists.
- Otherwise orchestrates Genderize + Agify + Nationalize and persists one profile row.

Response statuses:

- `201`: created
- `200`: already exists (`"message": "Profile already exists"`)
- `400`: missing/empty name
- `422`: invalid type
- `502`: upstream invalid response

#### GET /api/profiles/{profile_id}

- `200`: profile found
- `404`: not found

#### GET /api/profiles

Optional filters (case-insensitive):

- `gender`
- `country_id`
- `age_group`

Response shape:

```json
{
  "status": "success",
  "count": 2,
  "data": [
    {
      "id": "...",
      "name": "ella",
      "gender": "female",
      "age": 46,
      "age_group": "adult",
      "country_id": "DRC"
    }
  ]
}
```

#### DELETE /api/profiles/{profile_id}

- `204`: deleted
- `404`: profile not found

## 5. Data Contracts

### 5.1 Common error envelope

All route-level errors use:

```json
{
  "status": "error",
  "message": "<details>"
}
```

### 5.2 Stage 0 model highlights

`ClassifyData` fields:

- `name: str`
- `gender: str | null`
- `probability: float` constrained to `[0.0, 1.0]`
- `sample_size: int` constrained to `>= 0`
- `is_confident: bool`
- `processed_at: str` (UTC ISO-8601 with `Z`)

### 5.3 Stage 1 profile model highlights

`ProfileData` fields:

- `id: str` (generated UUID v7)
- `name: str`
- `gender: str`
- `gender_probability: float` `[0.0, 1.0]`
- `sample_size: int >= 0`
- `age: int >= 0`
- `age_group: child | teenager | adult | senior`
- `country_id: str`
- `country_probability: float` `[0.0, 1.0]`
- `created_at: str` (UTC ISO-8601 with `Z`)

## 6. Business Rules

### 6.1 Name validation

Stage 0 (`/classify`):

- Missing or blank -> `400`
- Multiple `name` values -> `422`

Stage 1 (`/profiles`):

- Missing or blank -> `400`
- Non-string -> `422`

### 6.2 Age group derivation

- `0-12`: `child`
- `13-19`: `teenager`
- `20-59`: `adult`
- `60+`: `senior`

### 6.3 Nationality derivation

- Select the country with the highest `probability` from Nationalize results.
- Empty or unusable country array is treated as upstream invalid response.

### 6.4 Idempotent profile creation

A profile is considered duplicate when `normalized_name` matches an existing row.

## 7. Persistence Design

The repository writes and reads from Supabase table `profiles`.

Read-select fields:

- `id`
- `name`
- `gender`
- `gender_probability`
- `sample_size`
- `age`
- `age_group`
- `country_id`
- `country_probability`
- `created_at`

Write-time normalized columns used for deterministic lookups and filtering:

- `normalized_name`
- `normalized_gender`
- `normalized_age_group`
- `normalized_country_id`

Recommended DB constraints/indexes:

- Unique index on `normalized_name`.
- Indexes on normalized filter columns for list endpoint performance.

## 8. Error Handling Strategy

### 8.1 Upstream failures

- Transport/parsing failures are converted to `UpstreamServiceError`.
- Invalid external payloads produce service-specific messages:
  - `Genderize returned an invalid response`
  - `Agify returned an invalid response`
  - `Nationalize returned an invalid response`

### 8.2 Global handlers

`main.py` adds global handlers for:

- `HTTPException`
- `RequestValidationError`
- fallback `Exception`

All are normalized to the same error envelope.

## 9. Environment Configuration

Required variables:

- `SUPABASE_URL`
- `SUPABASE_KEY` (or `SUPABASE_SERVICE_ROLE_KEY`)

`app/db.py` fails fast at startup if credentials are missing or the `profiles` table is inaccessible.

## 10. Local Development

Install:

```bash
pip install -r requirements.txt
```

Run:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Docs:

- Swagger UI: `http://localhost:8000/docs`
- OpenAPI: `http://localhost:8000/openapi.json`

Test suite:

```bash
pytest -q
```

Note: integration tests require reachable Supabase credentials in the environment.

## 11. Deployment and Containers

### 11.1 Docker

`docker-compose.yml` exposes port `8000:8000` for service `api`.

Current `Dockerfile` builds dependencies and copies `app/` only. Because startup command is `uvicorn main:app`, runtime also requires `main.py` in the image.

### 11.2 Render

`render.yaml` defines one Python web service:

- Build: `pip install -r requirements.txt`
- Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- `autoDeploy: false`

## 12. Test Coverage Snapshot

`tests/test_stage1_api.py` covers:

- Stage 0 success and validation/status mappings
- Stage 0 no-prediction behavior
- Stage 1 create success and contract fields
- Duplicate-name idempotency path
- Get-by-id success and not found
- List endpoint case-insensitive filtering
- Delete success and not found
- Upstream edge-case handling (`502`) and non-persistence guarantees

## 13. Known Technical Notes

- Requirement duplication exists in `requirements.txt` (`fastapi[all]` and version-pinned `fastapi`).
- `Dockerfile` should include `main.py` to ensure container startup works with `main:app`.

## 14. Suggested Next Improvements

- Add explicit DB migration/schema document for `profiles` table.
- Add health endpoint (`/healthz`) for orchestration probes.
- Add CI workflow for tests and linting.
- Add retry/backoff policy for external API transient failures.
