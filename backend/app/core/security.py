# app/core/security.py
from datetime import datetime, timedelta
from typing import Optional, Tuple
import uuid
from jose import jwt, JWTError
from passlib.context import CryptContext
from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(data: dict) -> str:
    """Crée un access token de courte durée (ex: 60 min)"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({
        "exp": expire,
        "type": "access",
        "iat": datetime.utcnow()
    })
    return jwt.encode(to_encode, settings.ACCESS_TOKEN_SECRET_KEY, algorithm=settings.ALGORITHM)

def create_refresh_token(data: dict) -> Tuple[str, str]:
    """
    Crée un refresh token de longue durée (ex: 30 jours)
    Retourne (token, jti) où jti est l'identifiant unique du token
    """
    to_encode = data.copy()
    jti = str(uuid.uuid4())  # Identifiant unique pour blacklist
    expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({
        "exp": expire,
        "type": "refresh",
        "jti": jti,
        "iat": datetime.utcnow()
    })
    token = jwt.encode(to_encode, settings.REFRESH_TOKEN_SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, jti

def decode_access_token(token: str) -> dict | None:
    """Décode un access token"""
    try:
        payload = jwt.decode(token, settings.ACCESS_TOKEN_SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != "access":
            return None
        return payload
    except JWTError:
        return None

def decode_refresh_token(token: str) -> dict | None:
    """Décode un refresh token"""
    try:
        payload = jwt.decode(token, settings.REFRESH_TOKEN_SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != "refresh":
            return None
        return payload
    except JWTError:
        return None

def get_token_expires_in_seconds(token: str, is_refresh: bool = False) -> int:
    """Retourne le nombre de secondes avant expiration du token"""
    try:
        if is_refresh:
            payload = decode_refresh_token(token)
        else:
            payload = decode_access_token(token)
        
        if payload and "exp" in payload:
            exp_timestamp = payload["exp"]
            now = datetime.utcnow().timestamp()
            return max(0, int(exp_timestamp - now))
    except:
        pass
    return 0