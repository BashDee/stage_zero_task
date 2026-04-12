# Gender Classifier API

A FastAPI app that exposes one endpoint to classify a name using Genderize and return a processed result.

## What This App Does

- Accepts a `name` query parameter
- Calls `https://api.genderize.io`
- Returns a normalized payload with:
  - `gender`
  - `probability`
  - `sample_size` (renamed from `count`)
  - `is_confident`
  - `processed_at` (UTC ISO 8601)

## Tech Stack

- Python 3.13
- FastAPI
- httpx
- Uvicorn

## Project Structure

- `main.py` - app startup, CORS, global exception handlers
- `app/api/routes.py` - HTTP route/view layer
- `app/services/classify.py` - validation and orchestration logic
- `app/services/genderize.py` - external API integration and response processing
- `app/models/classify.py` - response models

## Run Locally

1. Create/activate virtual environment (if needed)
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Start the app:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

4. Open docs:
- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

## Endpoint

### GET `/api/classify`

Query parameters:
- `name` (required)

Example request:

```bash
curl "http://localhost:8000/api/classify?name=bashir"
```

## Success Response

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

## Confidence Logic

`is_confident` is `true` only when both conditions are met:
- `probability >= 0.7`
- `sample_size >= 100`

Otherwise, `is_confident` is `false`.

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
- Invalid `name` shape (e.g. repeated values) -> `422 Unprocessable Entity`
- Upstream failure (Genderize unavailable/invalid payload) -> `502 Bad Gateway`
- Unexpected server error -> `500 Internal Server Error`

Special edge case:
- If Genderize returns `gender: null` or `count: 0`, response is:
  - Status `200 OK`
  - Message: `No prediction available for the provided name`

## CORS

CORS is enabled with wildcard origin support:
- `Access-Control-Allow-Origin: *`
