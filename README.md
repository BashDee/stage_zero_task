# Gender Classifier and Profiles API

A FastAPI app that supports Stage 0 classification and Stage 2 profile persistence/querying.

It also includes a GitHub OAuth PKCE client module under `/auth/github` and `/auth/github/callback` for stateless identity exchange.

## What This App Does

- Stage 0:
  - Accepts a `name` query parameter on `GET /api/classify`
  - Calls `https://api.genderize.io`
  - Returns a normalized classification payload
- Stage 2:
  - Accepts `POST /api/profiles` with `{ "name": "..." }`
  - Calls Genderize, Agify, and Nationalize APIs
  - Persists normalized profile records in Supabase Postgres
  - Exposes read/list/delete endpoints and natural-language search
  - Supports database-level filtering, sorting, and pagination
- Auth:
  - Redirects users to GitHub with PKCE at `GET /auth/github`
  - Exchanges the callback code at `GET /auth/github/callback`
  - Returns a normalized GitHub identity payload without issuing local session tokens

## Tech Stack

- Python 3.13
- FastAPI
- httpx
- Supabase (official Python client)
- Uvicorn

## Project Structure

- `main.py` - app startup, CORS, global exception handlers
- `app/api/routes.py` - HTTP route/view layer
- `app/db.py` - database initialization
- `app/models/classify.py` - Stage 0 response models
- `app/models/profile.py` - Stage 1 profile models
- `app/repositories/profiles.py` - profile persistence access layer
- `app/services/classify.py` - Stage 0 validation/orchestration logic
- `app/services/genderize.py` - Genderize integration
- `app/services/github_oauth.py` - GitHub OAuth PKCE flow and callback exchange
- `app/services/agify.py` - Agify integration
- `app/services/nationalize.py` - Nationalize integration
- `app/services/profiles.py` - Stage 2 profile orchestration
- `app/services/profile_search_parser.py` - rule-based natural-language parser
- `app/services/countries.py` - ISO country code/name resolution

## Environment Variables

- `GITHUB_CLIENT_ID` - required for GitHub OAuth authorization URL generation and token exchange
- `GITHUB_CLIENT_SECRET` - optional, for compatibility with GitHub OAuth app configurations that still provide a secret
- `GITHUB_OAUTH_SCOPE` - optional, defaults to `read:user user:email`
- `app/services/seed_profiles.py` - seed loading + idempotent insert logic
- `db/schema.sql` - canonical Stage 2 table definition
- `db/migrations/001_stage2_profiles.sql` - migration notes for Stage 1 to Stage 2
- `scripts/seed_profiles.py` - CLI for 2026-record idempotent seeding

## Run Locally

1. Create/activate virtual environment (if needed)
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Configure your Supabase credentials:

Windows PowerShell:

```powershell
$env:SUPABASE_URL="https://<project-ref>.supabase.co"
$env:SUPABASE_KEY="<service-role-or-anon-key>"
```

You can also use `SUPABASE_SERVICE_ROLE_KEY` instead of `SUPABASE_KEY`.

4. Start the app:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

5. Open docs:
- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

## Endpoints

### Stage 0

#### GET `/api/classify`

Query parameters:
- `name` (required)

Example request:

```bash
curl "http://localhost:8000/api/classify?name=bashir"
```

Success response example:

Status: `200 OK`

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

Confidence logic:

`is_confident` is `true` only when both conditions are met:
- `probability >= 0.7`
- `sample_size >= 100`

Otherwise, `is_confident` is `false`.

### Stage 2

#### POST `/api/profiles`
- Body: `{ "name": "ella" }`
- Creates and stores a profile from Genderize + Agify + Nationalize data
- Duplicate name returns existing profile with message `Profile already exists`

#### GET `/api/profiles/{id}`
- Returns a single persisted profile

#### GET `/api/profiles`
- Supports AND-combined filtering, sorting, and pagination in one request
- Filters: `gender`, `age_group`, `country_id`, `min_age`, `max_age`, `min_gender_probability`, `min_country_probability`
- Sorting: `sort_by=age|created_at|gender_probability`, `order=asc|desc`
- Pagination: `page` (default `1`), `limit` (default `10`, max `50`)

Success response shape:

```json
{
  "status": "success",
  "page": 1,
  "limit": 10,
  "total": 2,
  "data": [
    {
      "id": "018f9f48-49b1-7d34-aef3-06b7d2667adc",
      "name": "ella",
      "gender": "female",
      "gender_probability": 0.99,
      "age": 46,
      "age_group": "adult",
      "country_id": "KE",
      "country_name": "Kenya",
      "country_probability": 0.85,
      "created_at": "2026-04-01T12:00:00Z"
    }
  ]
}
```

#### GET `/api/profiles/search`
- Query param: `q`
- Optional pagination: `page`, `limit`
- Rule-based parser converts plain-English query into structured filters, then runs the same retrieval pipeline as `GET /api/profiles`

#### DELETE `/api/profiles/{id}`
- Returns `204 No Content` on success

## Error Format

All errors follow this structure:

```json
{
  "status": "error",
  "message": "<error message>"
}
```

## Validation and Error Cases

- Missing or empty `name` -> `400 Bad Request`
- Invalid `name` type -> `422 Unprocessable Entity`
- Profile not found -> `404 Not Found`
- Invalid list/search query params -> `422` with `{"status":"error","message":"Invalid query parameters"}`
- Missing or empty required `q` in search -> `400`
- Uninterpretable search query -> `400` with `{"status":"error","message":"Unable to interpret query"}`
- Upstream failure (Genderize/Agify/Nationalize invalid payload) -> `502 Bad Gateway`
- Unexpected server error -> `500 Internal Server Error`

Stage 1 edge cases (returns `502`, does not persist):
- Genderize returns `gender: null` or `count: 0`
- Agify returns `age: null`
- Nationalize returns no country data

## CORS

CORS is enabled with wildcard origin support:
- `Access-Control-Allow-Origin: *`

## Natural Language Parser (Stage 2)

The parser is deterministic and rule-based only. It does not use AI/LLM inference.

Supported keywords and mappings:
- Gender:
  - `male`, `males`, `man`, `men`, `boy`, `boys` -> `gender=male`
  - `female`, `females`, `woman`, `women`, `girl`, `girls` -> `gender=female`
  - If both male and female are present, gender is omitted (broad match)
- Age-group words:
  - `child`, `children` -> `age_group=child`
  - `teen`, `teens`, `teenager`, `teenagers` -> `age_group=teenager`
  - `adult`, `adults` -> `age_group=adult`
  - `senior`, `seniors` -> `age_group=senior`
- Age bounds:
  - `young` -> `min_age=16`, `max_age=24`
  - `above N`, `over N`, `older than N`, `at least N` -> `min_age=N`
  - `below N`, `under N`, `younger than N`, `at most N` -> `max_age=N`
- Country extraction:
  - `from <country>` resolves a country name/alias to ISO `country_id`

Required mapping examples:
- `young males` -> `gender=male`, `min_age=16`, `max_age=24`
- `females above 30` -> `gender=female`, `min_age=30`
- `people from angola` -> `country_id=AO`
- `adult males from kenya` -> `gender=male`, `age_group=adult`, `country_id=KE`
- `male and female teenagers above 17` -> `age_group=teenager`, `min_age=17`

Parsing flow and precedence:
1. Normalize query (lowercase, collapse spaces, remove punctuation).
2. Extract country phrase (`from ...`) using known aliases/ISO names.
3. Detect gender tokens (both genders means no gender filter).
4. Detect age-group tokens.
5. Detect numeric age bounds and `young` shorthand.
6. Combine all detected filters with AND semantics.

Limitations:
- Unsupported free-form phrasing without known keywords is rejected.
- Ambiguous phrasing that produces no recognized filters returns `Unable to interpret query`.
- Country extraction depends on known ISO names/aliases and `from <country>` style phrasing.

## Seeding 2026 Profiles

Seed file requirements:
- JSON array with 2026 unique profiles by `name`
- Required/derived fields align with the Stage 2 schema

Run seed:

```bash
python scripts/seed_profiles.py --file data/profiles_2026.json
```

Idempotency behavior:
- Existing profile names are preloaded.
- Only missing names are inserted.
- Re-running the same seed file does not create duplicates.
