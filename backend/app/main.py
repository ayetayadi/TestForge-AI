from fastapi import FastAPI
from contextlib import asynccontextmanager
import asyncio

from app.utils.common.embedding import preload_embedding_model
from app.api.project_api import router as project_router
from app.api.story_api import router as story_router
from app.api.job_api import router as job_router
from fastapi.middleware.cors import CORSMiddleware
from app.streaming.sse_manager import set_main_loop
from app.core.worker import start_workers
from app.llm.factory import get_llm
from app.db.base import Base
from app.core.database import engine

def preload_llms():
    print("[LLM] Preloading...")

    try:
        get_llm("analysis")
        get_llm("refinement")
        get_llm("ac_repair")
        print("[LLM] Ready")
    except Exception as e:
        print(f"[LLM ERROR] {e}")


def preload_models():
    print("[STARTUP] Preloading models...")

    try:
        preload_embedding_model()
    except Exception as e:
        print(f"[STARTUP] Embedding model error: {e}")

    try:
        preload_llms()
    except Exception as e:
        print(f"[STARTUP] LLM preload skipped: {e}")

    print("[STARTUP] Models ready!")


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[STARTUP] Initializing application...")

    print("[DB] Creating tables...")
    Base.metadata.create_all(bind=engine)
    print("[DB] Tables ready!")
    print("TABLES:", Base.metadata.tables.keys())

    # FIX event loop
    loop = asyncio.get_running_loop()
    set_main_loop(loop)

    preload_models()

    start_workers()

    print("[STARTUP] Application ready!")

    yield

    print("[SHUTDOWN] Cleaning up...")


app = FastAPI(
    title="TestForge AI Backend",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(project_router)
app.include_router(story_router)
app.include_router(job_router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"message": "TestForge AI Backend is running"}


@app.get("/debug/cache")
def debug_cache():
    try:
        from app.utils.common.embedding import get_cache_stats
        return get_cache_stats()
    except Exception as e:
        return {"error": str(e)}