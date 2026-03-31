from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):

    # =========================
    # ENCRYPTION KEY JIRA API   
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
    REDIS_CACHE_TTL: int = 604800         # 7 days in seconds
    REDIS_MAX_MEMORY: str = "100mb"       # Max Redis memory for embeddings

    # =========================
    # IN-MEMORY CACHE
    # =========================
    MEMORY_CACHE_SIZE: int = 500


    # =========================
    # RAG
    # =========================
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"
    EMBEDDING_DIM: int = 384              # Dimension of embeddings

    # =========================
    # TEMPERATURE
    # =========================
    ANALYSIS_TEMP: float = 0.0
    REFINEMENT_TEMP: float = 0.2
    AC_REPAIR_TEMP: float = 0.2

    # =========================
    # WORKER CONFIG
    # =========================
    MAX_WORKERS: int = 3

    # =========================
    # CONFIG
    # =========================
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )


settings = Settings()