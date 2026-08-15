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

import bcrypt

log = structlog.get_logger()
ALGORITHM = "HS256"

class AuthService:
    def hash_password(self, password: str) -> str:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
    def verify_password(self, plain: str, hashed: str) -> bool:
        try:
            return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
        except Exception:
            return False
    def create_access_token(self, user_id: str, email: str) -> str:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        payload = {"sub": str(user_id), "email": email, "exp": expire,
                   "iat": datetime.now(timezone.utc), "jti": str(uuid.uuid4()), "type": "access"}
        return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)
    def create_refresh_token(self, user_id: str) -> str:
        expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        payload = {"sub": str(user_id), "exp": expire, "jti": str(uuid.uuid4()), "type": "refresh"}
        return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)
    def decode_token(self, token: str) -> dict:
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
            return payload
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            )
    async def authenticate_user(self, db: AsyncSession, email: str, password: str) -> User:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user or not self.verify_password(password, user.hashed_password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")
        return user

bearer_scheme = HTTPBearer()
auth_service = AuthService()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = auth_service.decode_token(credentials.credentials)
    if payload.get("type") != "access":
        raise HTTPException(401, "Invalid token type")
    
    # Check if token is blacklisted in Redis
    try:
        from backend.services.market_data_service import get_redis
        redis = await get_redis()
        jti = payload.get("jti")
        if jti and await redis.get(f"revoked:{jti}"):
            raise HTTPException(401, "Token has been logged out")
    except HTTPException:
        raise
    except Exception as e:
        log.warning("Redis blacklist check bypassed", error=str(e))

    result = await db.execute(select(User).where(User.id == payload.get("sub")))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(401, "User not found")
    return user
