# app/main.py
# =========================
# ENV LOADING
# =========================
# from dotenv import load_dotenv
# load_dotenv()

# import os
# print("[LANGSMITH] TRACING:", os.getenv("LANGSMITH_TRACING"))
# print("[LANGSMITH] PROJECT:", os.getenv("LANGSMITH_PROJECT"))
# print("[LANGSMITH] API_KEY:", os.getenv("LANGSMITH_API_KEY", "")[:20] + "..." if os.getenv("LANGSMITH_API_KEY") else "NOT SET")


from contextlib import asynccontextmanager
import asyncio
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.admin import router as admin_router
from app.api.jira import router as jira_router
from app.api.users import router as users_router
from app.api.project import router as project_router
from app.api.user_story import router as story_router
from app.api.job import router as job_router
from app.api.pipeline import router as pipeline_router
from app.core.database import Base, engine
from app.llm.factory import get_llm
from app.streaming.sse_manager import set_main_loop
from app.core.embedding import preload_embedding_model
from app.core.config import settings
from app.workers.asyncio_workers import start_workers , stop_workers

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

    await asyncio.to_thread(preload_models)
    
    await start_workers()
    print("[STARTUP] Application ready!")

    yield

    # Arrêt
    print("[SHUTDOWN] Stopping workers...")
    await stop_workers()
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
app.include_router(pipeline_router)

# =========================
# HEALTH
# =========================
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ping")
async def ping():
    return {"status": "ok"}