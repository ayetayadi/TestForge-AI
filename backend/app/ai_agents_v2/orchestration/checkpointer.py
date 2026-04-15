from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.memory import MemorySaver
from app.core.config import settings


def create_checkpointer():
    """
    Crée le checkpointer approprié selon l'environnement.
    - Production : PostgreSQL (persistant)
    - Dev/Test : MemorySaver (RAM)
    """
    if settings.ENV == "production":
        checkpointer = PostgresSaver.from_conn_string(
            settings.CHECKPOINT_DB_URL
        )
        # Créer les tables si elles n'existent pas
        checkpointer.setup()
        return checkpointer
    else:
        return MemorySaver()


# Singleton global
checkpointer = create_checkpointer()