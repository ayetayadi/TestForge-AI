from cryptography.fernet import Fernet
from app.core.config import settings

fernet = Fernet(settings.ENCRYPTION_KEY.encode())


def encrypt(value: str) -> str:
    if not value:
        return value
    return fernet.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    if not value:
        return value
    return fernet.decrypt(value.encode()).decode()