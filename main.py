from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.auth import router as auth_router
from app.api.routes import router
from app.db import init_db
from app.repositories.tokens import TokenRepository
from app.repositories.users import UserRepository
from app.services.github_oauth import InMemoryOAuthStateStore
from app.services.jwt import JWTService
from app.services.token_manager import TokenManager
from app.services.users import UserService


@asynccontextmanager
async def lifespan(app: FastAPI):
    from httpx import AsyncClient, Timeout

    init_db()
    
    # Initialize HTTP client
    app.state.http_client = AsyncClient(timeout=Timeout(5.0))
    
    # Initialize GitHub OAuth state store
    app.state.github_oauth_state_store = InMemoryOAuthStateStore()
    
    # Initialize token services
    from app.db import get_supabase_client
    
    supabase = get_supabase_client()
    app.state.jwt_service = JWTService()
    app.state.token_repository = TokenRepository(supabase)
    app.state.token_manager = TokenManager(app.state.jwt_service, app.state.token_repository)
    
    # Initialize user services
    app.state.user_repository = UserRepository(supabase)
    app.state.user_service = UserService(app.state.user_repository)
    
    try:
        yield
    finally:
        await app.state.http_client.aclose()


app = FastAPI(
    title="Gender Classifier API",
    version="1.0.0",
    description="Processes Genderize responses into a simplified classification payload.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "message": str(exc.detail)},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError):
    message = "Invalid request"
    if exc.errors():
        first_error = exc.errors()[0]
        message = first_error.get("msg", message)
    return JSONResponse(
        status_code=422,
        content={"status": "error", "message": message},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, __: Exception):
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "Internal server error"},
    )


app.include_router(router)
app.include_router(auth_router)
