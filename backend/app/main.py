from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.admin import router as admin_router
from app.api.jira import router as jira_router
from app.api.users import router as users_router
from app.api.projects import router as project_router
from app.api.stories import router as story_router
from app.api.jobs import router as job_router

from app.core.database import Base, engine
from app.core.worker import start_workers
from app.llm.factory import get_llm
from app.streaming.sse_manager import set_main_loop
from app.utils.common.embedding import preload_embedding_model


def preload_llms() -> None:
    print("[LLM] Preloading...")

    try:
        get_llm("analysis")
        get_llm("refinement")
        get_llm("ac_repair")
        print("[LLM] Ready")
    except Exception as e:
        print(f"[LLM ERROR] {e}")


def preload_models() -> None:
    print("[STARTUP] Preloading models...")

    try:
        preload_embedding_model()
        print("[EMBEDDING] Ready")
    except Exception as e:
        print(f"[EMBEDDING ERROR] {e}")

    try:
        preload_llms()
    except Exception as e:
        print(f"[STARTUP] LLM preload skipped: {e}")

    print("[STARTUP] Models ready!")


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[STARTUP] Initializing application...")

    print("[DB] Creating tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[DB] Tables ready!")
    print("TABLES:", Base.metadata.tables.keys())

    loop = asyncio.get_running_loop()
    set_main_loop(loop)

    preload_models()
    start_workers()

    print("[STARTUP] Application ready!")
    yield
    print("[SHUTDOWN] Cleaning up...")


app = FastAPI(
    title="TestForge AI Backend",
    lifespan=lifespan,
)

origins = [
    "http://localhost:4200",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,   # use ["*"] only if you do NOT use credentials
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=600,
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
app.include_router(job_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ping")
async def ping():
    return {"status": "ok"}