# backend/services/auth_service.py
"""
JWT authentication with refresh token rotation.

Security decisions:
- Access tokens: short-lived (15min–24h), stateless JWTs
- Refresh tokens: longer-lived (30 days), stored in DB for revocation
- Passwords: bcrypt with cost factor 12 (slow enough to resist brute force)
- Token storage: client stores access token in memory only
  (NOT localStorage — XSS vulnerable). Refresh token in httpOnly cookie.

Why httpOnly cookies for refresh tokens?
- JavaScript cannot read httpOnly cookies (XSS protection)
- Automatically sent with requests (convenience)
- SameSite=Strict prevents CSRF

Why NOT store access tokens in localStorage?
- localStorage is accessible to any JS running on the page
- XSS attacks can steal tokens permanently
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid

from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from backend.core.config import settings
from backend.core.database import get_db
from backend.models.user import User

log = structlog.get_logger()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

ALGORITHM = "HS256"


class AuthService:

    def hash_password(self, password: str) -> str:
        return pwd_context.hash(password)

    def verify_password(self, plain: str, hashed: str) -> bool:
        return pwd_context.verify(plain, hashed)

    def create_access_token(self, user_id: str, email: str) -> str:
        """
        Short-lived JWT for API authentication.
        Contains minimal claims — don't put sensitive data in JWT payload
        (it's base64-encoded, not encrypted).
        """
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
        payload = {
            "sub": str(user_id),
            "email": email,
            "exp": expire,
            "iat": datetime.now(timezone.utc),
            "jti": str(uuid.uuid4()),  # JWT ID — enables token blacklisting
            "type": "access",
        }
        return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)

    def create_refresh_token(self, user_id: str) -> str:
        """Longer-lived token stored in httpOnly cookie."""
        expire = datetime.now(timezone.utc) + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )
        payload = {
            "sub": str(user_id),
            "exp": expire,
            "jti": str(uuid.uuid4()),
            "type": "refresh",
        }
        return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)

    def decode_token(self, token: str) -> dict:
        """
        Decode and validate JWT. Raises HTTPException on any failure.
        Never expose the raw JWTError to the client — it leaks info.

        PHASE 2.2 FIX: this previously did manual expiry checking AFTER
        jwt.decode() had already run:

            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
            if payload.get("exp") and datetime.fromtimestamp(
                payload["exp"], tz=timezone.utc
            ) < datetime.now(timezone.utc):
                raise HTTPException(... "Token expired" ...)

        This was redundant, not broken: python-jose's jwt.decode() already
        validates the `exp` claim internally by default and raises
        jose.exceptions.ExpiredSignatureError (a subclass of JWTError) for
        an expired token, which the existing `except JWTError` clause below
        already catches. The manual block never actually fired in practice
        — by the time control reached it, jwt.decode() would already have
        raised on an expired token. It added a second, parallel expiry
        implementation that could in principle drift from python-jose's
        own clock-skew handling (jose allows a small leeway) and made the
        function harder to reason about for no behavioural benefit.
        Removed; jwt.decode()'s built-in validation is the single source
        of truth for expiry now.

        One real behavioural difference callers should be aware of: the
        previous code returned a generic 401 "Token expired" for an
        expired token specifically, distinct from "Invalid token" for
        other failures. That distinction is now collapsed into one
        message ("Invalid token") for both cases, via the except JWTError
        branch — which is intentional: from a security standpoint you
        generally do NOT want to tell a caller "your token format was
        fine, it just expired" vs "your token was garbage", since that
        distinction can help an attacker calibrate token-forging attempts.
        If you need expired-vs-invalid differentiation for your own
        frontend UX (e.g. to silently trigger a refresh on FIRST seeing
        the token has merely expired, rather than logging the user out
        for ANY failure), catch jose.ExpiredSignatureError specifically
        as its own except clause above the general JWTError one.
        """
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
            return payload
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    async def authenticate_user(
        self, db: AsyncSession, email: str, password: str
    ) -> User:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user or not self.verify_password(password, user.hashed_password):
            # Same error regardless of whether user exists — prevents enumeration
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account disabled",
            )

        return user


# ---- FastAPI dependency for protected routes ----

bearer_scheme = HTTPBearer()
auth_service = AuthService()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    FastAPI dependency — validates JWT and returns the current user.
    Use on any protected endpoint: user: User = Depends(get_current_user)
    """
    payload = auth_service.decode_token(credentials.credentials)
    user_id = payload.get("sub")
    token_type = payload.get("type")

    if token_type != "access":
        raise HTTPException(401, "Invalid token type")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(401, "User not found")

    return user