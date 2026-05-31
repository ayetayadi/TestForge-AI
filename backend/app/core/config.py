import os

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
    # ENVIRONMENT
    # =========================
    ENV: str = "dev"

    # =========================
    # DATABASE / AUTH
    # =========================
    DATABASE_URL: str

    @property
    def CHECKPOINT_DB_URL(self) -> str:
        return self.DATABASE_URL.replace(
            "postgresql+asyncpg://",
            "postgresql://"
        )
    
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    REFRESH_TOKEN_SECRET_KEY: str | None = None

    # =========================
    # JIRA / FRONTEND
    # =========================
    JIRA_CLIENT_ID: str
    JIRA_CLIENT_SECRET: str
    JIRA_REDIRECT_URI: str = "http://localhost:8000/jira/callback"
    FRONTEND_URL: str = "http://localhost:4200"
    # Comma-separated CORS origins — override in .env for production
    ALLOWED_ORIGINS: str = "http://localhost:4200"

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
    OPENROUTER_API_KEY_1: str | None = None
    OPENROUTER_API_KEY_2: str | None = None
    OPENROUTER_API_KEY_3: str | None = None
    OPENROUTER_API_KEY_4: str | None = None
    OPENROUTER_API_KEY_5: str | None = None
    OPENROUTER_API_KEY_6: str | None = None

    GROQ_API_KEY_1: str | None = None
    GROQ_API_KEY_2: str | None = None
    GROQ_API_KEY_3: str | None = None
    GROQ_API_KEY_4: str | None = None
    GROQ_API_KEY_5: str | None = None

    # =========================
    # Hugging Face CONFIG
    # =========================
    HF_TOKEN: str | None = None

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
    # EMBEDDINGS
    # =========================
    EMBEDDING_MODEL: str = "paraphrase-multilingual-MiniLM-L12-v2"
    EMBEDDING_DIM: int = 384

    # =========================
    # WORKER CONFIG
    # =========================
    MAX_WORKERS: int = 5
    # =========================
    # MAIL CONFIG
    # =========================
    MAIL_USERNAME: str
    MAIL_PASSWORD: str
    MAIL_FROM: str
    MAIL_FROM_NAME: str = "TestForge"

    # =========================
    # MCP / PLAYWRIGHT CONFIG
    # =========================
    TEST_APPLICATION_URL: str = "http://localhost:3000"

    # =========================
    # TESTOMAT.IO CONFIG
    # =========================
    TESTOMATIO_API_KEY: str | None = None

    # =========================
    # LANGFUSE CONFIG
    # =========================
    LANGFUSE_PUBLIC_KEY: str | None = None
    LANGFUSE_SECRET_KEY: str | None = None
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"

    # =========================
    # DEEPEVAL CONFIG
    # =========================
    DEEPEVAL_API_KEY: str | None = None

    # =========================
    # AZURE OPENAI CONFIG (juge LLM pour l'évaluation)
    # =========================
    AZURE_OPENAI_ENDPOINT_JUDGE: str | None = None
    AZURE_OPENAI_KEY_JUDGE: str | None = None
    AZURE_OPENAI_DEPLOYMENT_JUDGE: str = "gpt-4.1"
    AZURE_OPENAI_API_VERSION_JUDGE: str = "2025-01-01-preview"

    # =========================
    # LANGSMITH CONFIG
    # =========================
    LANGSMITH_API_KEY: str | None = None
    LANGSMITH_TRACING: str | None = None
    LANGSMITH_ENDPOINT: str = "https://api.smith.langchain.com"
    LANGCHAIN_PROJECT: str = "TestForge-Eval"


settings = Settings()