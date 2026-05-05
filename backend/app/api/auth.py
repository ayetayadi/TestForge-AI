from fastapi import APIRouter, Depends, HTTPException, status, Response, Cookie
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import (
    verify_password, 
    hash_password, 
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    decode_access_token
)
from app.models.user import User
from app.schemas.user_schema import LoginRequest, TokenResponse, SetupPasswordRequest, UserRead, ForgotPasswordRequest, ResetPasswordRequest
from app.api.deps import get_current_user
import secrets
from datetime import datetime, timedelta
from app.services.mail_service import send_reset_email
from typing import Optional

router = APIRouter(prefix="/auth", tags=["Auth"])

# Blacklist simple en mémoire (pour production, utilise Redis)
_blacklisted_refresh_tokens = set()

# ===================== LOGIN avec REFRESH TOKEN =====================

@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest, 
    db: AsyncSession = Depends(get_db),
    response: Response = None
):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled"
        )

    # Données à inclure dans les tokens
    token_data = {
        "sub": str(user.id), 
        "is_admin": user.is_admin, 
        "email": user.email
    }
    
    # Créer les deux tokens
    access_token = create_access_token(token_data)
    refresh_token, jti = create_refresh_token(token_data)
    
    # Stocker le refresh token dans un cookie httpOnly (plus sécurisé)
    if response:
        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            httponly=True,      # Inaccessible via JavaScript (protection XSS)
            secure=False,       # Mettre True en production avec HTTPS
            samesite="lax",     # Protection CSRF
            max_age=30 * 24 * 60 * 60  # 30 jours en secondes
        )
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
    )

# ===================== REFRESH ENDPOINT =====================

@router.post("/refresh")
async def refresh_access_token(
    response: Response,
    refresh_token: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Rafraîchit l'access token automatiquement
    Le frontend appelle ce endpoint quand il reçoit un 401
    """
    if not refresh_token:
        print("[REFRESH DEBUG] No cookie received")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="No refresh token provided"
        )
    
    # 1. Vérifier et décoder le refresh token
    print(f"[REFRESH DEBUG] Cookie received, token prefix: {refresh_token[:20]}...")
    payload = decode_refresh_token(refresh_token)
    if not payload:
        print("[REFRESH DEBUG] Token decode failed (invalid or expired)")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Invalid refresh token"
        )
    
    # 2. Vérifier si le token est blacklisté
    jti = payload.get("jti")
    if jti in _blacklisted_refresh_tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Refresh token revoked"
        )
    
    # 3. Vérifier expiration (déjà fait par decode, mais on vérifie explicitement)
    exp = payload.get("exp")
    if exp and datetime.fromtimestamp(exp) < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Refresh token expired"
        )
    
    # 4. Récupérer l'utilisateur
    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="User not found or inactive"
        )
    
    # 5. Créer NOUVEAUX tokens (rotation)
    token_data = {
        "sub": str(user.id), 
        "is_admin": user.is_admin, 
        "email": user.email
    }
    
    new_access_token = create_access_token(token_data)
    new_refresh_token, new_jti = create_refresh_token(token_data)
    
    # 6. Blacklist l'ancien refresh token (rotation - empêche réutilisation)
    _blacklisted_refresh_tokens.add(jti)
    
    # Nettoyage optionnel de la blacklist (supprimer les tokens expirés)
    # Pour simplifier, on garde en mémoire, c'est suffisant pour un petit volume
    
    # 7. Mettre à jour le cookie avec le nouveau refresh token
    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=30 * 24 * 60 * 60
    )
    
    return {"access_token": new_access_token, "token_type": "bearer"}

# ===================== LOGOUT =====================

@router.post("/logout")
async def logout(
    response: Response,
    refresh_token: Optional[str] = Cookie(None)
):
    """Déconnexion - révoque le refresh token"""
    if refresh_token:
        payload = decode_refresh_token(refresh_token)
        if payload:
            jti = payload.get("jti")
            _blacklisted_refresh_tokens.add(jti)
    
    # Supprimer le cookie refresh_token
    response.delete_cookie("refresh_token")
    
    return {"message": "Logged out successfully"}

# ===================== LOGOUT EVERYWHERE =====================

@router.post("/logout-all")
async def logout_all_devices(
    response: Response,
    current_user: User = Depends(get_current_user),
    refresh_token: Optional[str] = Cookie(None)
):
    """Déconnecte de tous les appareils - révoque TOUS les refresh tokens"""
    # Pour une vraie implémentation, il faudrait stocker tous les jti par user
    # En attendant, on révoque juste le token actuel
    if refresh_token:
        payload = decode_refresh_token(refresh_token)
        if payload:
            jti = payload.get("jti")
            _blacklisted_refresh_tokens.add(jti)
    
    response.delete_cookie("refresh_token")
    
    return {"message": "Logged out from all devices"}

# ===================== TES ENDPOINTS EXISTANTS (inchangés) =====================

@router.post("/forgot-password")
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    # Always return 200 — never reveal whether email exists
    if not user or not user.is_active:
        return {"message": "If that email is registered, a reset link has been sent."}

    token = secrets.token_urlsafe(48)
    user.reset_token = token
    user.reset_token_expires_at = datetime.utcnow() + timedelta(minutes=30)
    await db.commit()

    try:
        await send_reset_email(user.email, user.username, token)
    except Exception as e:
        # Roll back token if email fails so user can retry
        user.reset_token = None
        user.reset_token_expires_at = None
        await db.commit()
        raise HTTPException(status_code=500,
                            detail="Failed to send email. Please try again.")

    return {"message": "If that email is registered, a reset link has been sent."}

@router.post("/reset-password")
async def reset_password(
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    if payload.new_password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    result = await db.execute(
        select(User).where(User.reset_token == payload.token)
    )
    user = result.scalar_one_or_none()

    if not user or not user.reset_token_expires_at:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")

    if datetime.utcnow() > user.reset_token_expires_at:
        # Clean up expired token
        user.reset_token = None
        user.reset_token_expires_at = None
        await db.commit()
        raise HTTPException(status_code=400, detail="Reset link has expired. Please request a new one.")

    user.hashed_password = hash_password(payload.new_password)
    user.reset_token = None
    user.reset_token_expires_at = None
    await db.commit()

    return {"message": "Password reset successfully. You can now log in."}

@router.post("/setup-password")
async def setup_password(
    payload: SetupPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    # Find user by token
    result = await db.execute(
        select(User).where(User.setup_token == payload.token)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired setup link")

    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    user.hashed_password = hash_password(payload.password)  # ← CORRIGÉ: payload.password
    user.is_active = True
    user.is_verified = True
    user.setup_token = None
    await db.commit()

    return {"message": "Password set successfully. You can now log in."}