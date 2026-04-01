from contextlib import asynccontextmanager
import asyncio
import os

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
from app.core.embedding import preload_embedding_model
from app.core.config import settings


# =========================
# LLM
# =========================
def preload_llms():
    print("[LLM] Preloading...")
    try:
        get_llm("analysis")
        get_llm("refinement")
        get_llm("ac_repair")
        print("[LLM] Ready")
    except Exception as e:
        print(f"[LLM ERROR] {e}")


# =========================
# MODELS
# =========================
def preload_models():
    print("[STARTUP] Preloading models...")

    preload_embedding_model()
    preload_llms()

    print("[STARTUP] Models ready!")


# =========================
# LIFESPAN
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[STARTUP] Initializing application...")

    # HF TOKEN
    if settings.HF_TOKEN:
        os.environ["HF_TOKEN"] = settings.HF_TOKEN
        print("[HF] Token loaded")

    # DB
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[DB] Tables ready!")

    # SSE loop
    loop = asyncio.get_running_loop()
    set_main_loop(loop)

    # Models (non-blocking)
    await asyncio.to_thread(preload_models)

    # Workers
    workers = await start_workers()

    print("[STARTUP] Application ready!")

    yield

    print("[SHUTDOWN] Cleaning up...")

    # Stop workers
    for task in workers:
        task.cancel()

    await asyncio.gather(*workers, return_exceptions=True)

    print("[SHUTDOWN] Workers stopped")


# =========================
# APP
# =========================
app = FastAPI(
    title="TestForge AI Backend",
    lifespan=lifespan,
)


# =========================
# CORS
# =========================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
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
app.include_router(job_router)


# =========================
# HEALTH
# =========================
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ping")
async def ping():
    return {"status": "ok"}