# backend/api/routers/auth.py
"""
Authentication endpoints.
Minimal but complete: register, login, refresh, logout.
"""
from fastapi import APIRouter, Depends, HTTPException, Response, Cookie
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
import uuid

from backend.core.config import settings
from backend.core.database import get_db
from backend.models.user import User
from backend.services.auth_service import AuthService, get_current_user

router = APIRouter()
auth_service = AuthService()

REFRESH_COOKIE_NAME = "qp_refresh"

# PHASE 2.2 FIX: this was hardcoded to True:
#     COOKIE_SECURE = True
# The Secure cookie attribute tells the browser "only ever send this
# cookie over HTTPS." That's exactly right for production, but local
# development almost always runs the backend over plain HTTP
# (http://localhost:8000) — with COOKIE_SECURE hardcoded True, the
# browser would silently refuse to store or send the refresh-token
# cookie at all during local dev. The practical symptom: /auth/login
# appears to succeed (200, access token returned), but /auth/refresh
# always fails with "No refresh token" because the cookie never made
# it to the browser in the first place. No error pointed at the actual
# cause — it just looked like refresh was broken.
#
# Fixed by deriving this from settings.DEBUG instead of hardcoding it:
# secure cookies in production (DEBUG=False), non-secure (but still
# httpOnly + sameSite=strict) cookies in local dev (DEBUG=True), so
# local HTTP testing works without weakening the production posture.
COOKIE_SECURE = not settings.DEBUG
COOKIE_SAMESITE = "strict"


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    risk_tolerance: str = Field("moderate", pattern="^(conservative|moderate|aggressive)$")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int   # seconds


class UserResponse(BaseModel):
    id: str
    email: str
    risk_tolerance: str


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(request: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Create a new user account."""
    # Check email not already taken
    result = await db.execute(select(User).where(User.email == request.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=request.email,
        hashed_password=auth_service.hash_password(request.password),
        risk_tolerance=request.risk_tolerance,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    return UserResponse(
        id=str(user.id),
        email=user.email,
        risk_tolerance=user.risk_tolerance,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    Authenticate and return JWT tokens.
    Access token returned in body.
    Refresh token set as httpOnly cookie.
    """
    user = await auth_service.authenticate_user(db, request.email, request.password)

    access_token = auth_service.create_access_token(str(user.id), user.email)
    refresh_token = auth_service.create_refresh_token(str(user.id))

    # Set refresh token as httpOnly cookie (XSS-safe)
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=60 * 60 * 24 * 30,  # 30 days
        path="/api/v1/auth",         # Scoped — only sent to auth endpoints
    )

    return TokenResponse(
        access_token=access_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    response: Response,
    db: AsyncSession = Depends(get_db),
    refresh: Optional[str] = Cookie(None, alias=REFRESH_COOKIE_NAME),
):
    """
    Exchange a refresh token for a new access token.
    Called automatically by the frontend on page load (silent refresh).
    """
    if not refresh:
        raise HTTPException(status_code=401, detail="No refresh token")

    payload = auth_service.decode_token(refresh)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    result = await db.execute(
        select(User).where(User.id == payload["sub"])
    )
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found")

    new_access = auth_service.create_access_token(str(user.id), user.email)
    new_refresh = auth_service.create_refresh_token(str(user.id))

    response.set_cookie(
        key=REFRESH_COOKIE_NAME, value=new_refresh,
        httponly=True, secure=COOKIE_SECURE, samesite=COOKIE_SAMESITE,
        max_age=60 * 60 * 24 * 30, path="/api/v1/auth",
    )

    return TokenResponse(
        access_token=new_access,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.delete("/logout")
async def logout(response: Response):
    """Clear the refresh token cookie."""
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/api/v1/auth")
    return {"detail": "Logged out"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Return the authenticated user's profile."""
    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        risk_tolerance=current_user.risk_tolerance,
    )