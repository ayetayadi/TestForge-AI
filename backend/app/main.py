# app/main.py
# ENV must load before any app import so langfuse auto-initialises with real credentials.
from dotenv import load_dotenv
load_dotenv()

# =========================
# LOGGING
# =========================
import logging
import uuid
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("mcp").setLevel(logging.INFO)

logger = logging.getLogger(__name__)

from contextlib import asynccontextmanager
import asyncio
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.auth import router as auth_router
from app.api.admin import router as admin_router
from app.api.jira import router as jira_router
from app.api.users import router as users_router
from app.api.projects import router as project_router
from app.api.user_stories import router as story_router
from app.api.pipeline import router as pipeline_router
from app.api.versions import router as versions_router
from app.api.test_cases import router as test_cases_router
from app.api.playwright import router as playwright_router
from app.api.dashboard import router as dashboard_router
from app.api.defects import router as defects_router
from app.api.notifications import router as notifications_router
from app.api.sync_jira import router as sync_jira_router
from app.api.risks import router as risk_router
from app.api.test_plans import router as test_plans_router
from app.api.test_suites import router as test_suites_router
from app.api.chatbot import router as chatbot_router
from app.api.testomat import router as testomat_router
from app.core.database import Base, engine
from app.streaming.sse_manager import set_main_loop
from app.core.model_manager import preload_embedding_model
from app.core.config import settings
from app.workers.us_worker import start_workers, stop_workers
from app.workers.risk_worker import start_risk_workers, stop_risk_workers
from app.workers.tc_worker import start_tc_workers, stop_tc_workers


# =========================
# BOOT VALIDATION
# Fail fast with a clear message if critical env vars are absent.
# =========================
def _validate_required_settings() -> None:
    required = {
        "DATABASE_URL": settings.DATABASE_URL,
        "ACCESS_TOKEN_SECRET_KEY": settings.ACCESS_TOKEN_SECRET_KEY,
        "ENCRYPTION_KEY": settings.ENCRYPTION_KEY,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise RuntimeError(
            f"[BOOT] Missing required environment variables: {', '.join(missing)}. "
            "Check your .env file and restart."
        )
    logger.info("[BOOT] All required environment variables present.")


# =========================
# MIDDLEWARE — Request ID
# =========================
class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attaches a unique X-Request-ID to every request for tracing."""
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        logger.debug(
            f"{request.method} {request.url.path} "
            f"→ {response.status_code} ({duration_ms:.1f}ms) [{request_id}]"
        )
        return response


# =========================
# MIDDLEWARE — Rate Limiter
# Simple in-memory limiter. No extra packages required.
# /auth/login and /auth/refresh: 10 req/min per IP.
# =========================
class RateLimitMiddleware(BaseHTTPMiddleware):
    _RATE_LIMITED_PATHS = {"/auth/login", "/auth/refresh"}
    _MAX_REQUESTS = 10
    _WINDOW_SECONDS = 60

    def __init__(self, app):
        super().__init__(app)
        self._hits: dict[str, list[float]] = {}

    async def dispatch(self, request: Request, call_next):
        if request.url.path not in self._RATE_LIMITED_PATHS:
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"
        key = f"{ip}:{request.url.path}"
        now = time.monotonic()

        window_start = now - self._WINDOW_SECONDS
        hits = [t for t in self._hits.get(key, []) if t > window_start]

        if len(hits) >= self._MAX_REQUESTS:
            logger.warning(f"[RATE LIMIT] {ip} exceeded limit on {request.url.path}")
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please wait a moment and try again."},
                headers={"Retry-After": str(self._WINDOW_SECONDS)},
            )

        hits.append(now)
        self._hits[key] = hits
        return await call_next(request)


# =========================
# LIFESPAN
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("[STARTUP] Validating configuration...")
    _validate_required_settings()

    if settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY:
        from app.core.observability import init_langfuse
        init_langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST,
        )
        logger.info("[LANGFUSE] Tracing enabled")
    else:
        logger.info("[LANGFUSE] Keys not set — tracing disabled")

    from app.core.observability import init_deepeval
    init_deepeval()

    if settings.HF_TOKEN:
        os.environ["HF_TOKEN"] = settings.HF_TOKEN
        logger.info("[HF] Token loaded")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("[DB] Tables ready")

    loop = asyncio.get_running_loop()
    set_main_loop(loop)

    await asyncio.to_thread(preload_embedding_model)

    await start_workers()
    await start_risk_workers()
    await start_tc_workers()
    logger.info("[STARTUP] Application ready")

    yield

    logger.info("[SHUTDOWN] Stopping workers...")
    await stop_workers()
    await stop_risk_workers()
    await stop_tc_workers()
    logger.info("[SHUTDOWN] Workers stopped")

    from app.core.observability import is_langfuse_enabled
    if is_langfuse_enabled():
        from langfuse import get_client
        get_client().flush()
        logger.info("[LANGFUSE] Flushed pending spans")


# =========================
# APP
# =========================
_IS_DEV = settings.ENV in ("dev", "local", "development")

app = FastAPI(
    title="TestForge AI Backend",
    lifespan=lifespan,
    # Interactive API docs only in dev — hidden in production
    docs_url="/docs" if _IS_DEV else None,
    redoc_url="/redoc" if _IS_DEV else None,
    openapi_url="/openapi.json" if _IS_DEV else None,
)


# =========================
# GLOBAL EXCEPTION HANDLER
# Logs full traceback internally; returns a clean 500 to the client.
# =========================
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "n/a")
    logger.error(
        f"[UNHANDLED] {request.method} {request.url.path} "
        f"[request_id={request_id}] — {type(exc).__name__}: {exc}",
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred. Please try again later."},
        headers={"X-Request-ID": request_id},
    )


# =========================
# MIDDLEWARES
# Order matters: added in reverse (last added = outermost)
# =========================
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.ALLOWED_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# ROUTERS
# =========================
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(jira_router)
app.include_router(users_router)
app.include_router(project_router)
app.include_router(story_router)
app.include_router(pipeline_router)
app.include_router(versions_router)
app.include_router(test_cases_router)
app.include_router(playwright_router)
app.include_router(dashboard_router)
app.include_router(defects_router)
app.include_router(notifications_router)
app.include_router(sync_jira_router)
app.include_router(risk_router)
app.include_router(test_plans_router)
app.include_router(test_suites_router)
app.include_router(chatbot_router)
app.include_router(testomat_router)


# =========================
# HEALTH CHECK — tests real DB connectivity
# =========================
@app.get("/health", tags=["System"])
async def health():
    from sqlalchemy import text
    from app.core.database import async_session_maker
    try:
        async with async_session_maker() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        logger.error(f"[HEALTH] Database check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": "unreachable"},
        )


@app.get("/ping", tags=["System"])
async def ping():
    return {"status": "ok"}
