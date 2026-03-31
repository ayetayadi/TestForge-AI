from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # =========================
    # GENERAL CONFIG
    # =========================
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    # =========================
    # DATABASE / AUTH
    # =========================
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    # =========================
    # JIRA / FRONTEND
    # =========================
    JIRA_URL: str
    JIRA_CLIENT_ID: str
    JIRA_CLIENT_SECRET: str
    JIRA_REDIRECT_URI: str = "http://localhost:8000/jira/callback"
    FRONTEND_URL: str = "http://localhost:4200"

    # =========================
    # ENCRYPTION
    # =========================
    ENCRYPTION_KEY: str

    # =========================
    # LLM CONFIG
    # =========================
    LLM_PROVIDER: str = "smart"
    GEMINI_API_KEY: str | None = None
    OPENROUTER_API_KEY: str | None = None
    GROQ_API_KEY: str | None = None

    # =========================
    # REDIS CONFIG
    # =========================
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0
    REDIS_CACHE_TTL: int = 604800
    REDIS_MAX_MEMORY: str = "100mb"

    # =========================
    # IN-MEMORY CACHE
    # =========================
    MEMORY_CACHE_SIZE: int = 500

    # =========================
    # RAG / EMBEDDINGS
    # =========================
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"
    EMBEDDING_DIM: int = 384

    # =========================
    # TEMPERATURES
    # =========================
    ANALYSIS_TEMP: float = 0.0
    REFINEMENT_TEMP: float = 0.2
    AC_REPAIR_TEMP: float = 0.2

    # =========================
    # WORKER CONFIG
    # =========================
    MAX_WORKERS: int = 3

    # =========================
    # MAIL CONFIG
    # =========================
    MAIL_USERNAME: str
    MAIL_PASSWORD: str
    MAIL_FROM: str
    MAIL_FROM_NAME: str = "TestForge"


settings = Settings()