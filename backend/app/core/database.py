from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.core.config import settings

# 1. définir Base AVANT tout
Base = declarative_base()

# 2. importer les modèles APRÈS
import app.models

# =========================
# ENGINE — production-grade pool
# =========================
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_size=20,        # max persistent connections
    max_overflow=10,     # extra connections allowed under burst load
    pool_recycle=3600,   # recycle connections hourly (avoids stale conn errors)
    pool_pre_ping=True,  # test liveness before handing connection to app
    pool_timeout=30,     # wait up to 30 s for a free slot
)

# =========================
# SESSION
# =========================
async_session_maker  = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# =========================
# DEPENDENCY
# =========================
async def get_db():
    async with async_session_maker() as session:
        yield session