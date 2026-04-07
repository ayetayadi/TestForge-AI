from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.core.config import settings

# 1. définir Base AVANT tout
Base = declarative_base()

# 2. importer les modèles APRÈS
import app.models

# =========================
# ENGINE
# =========================
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
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