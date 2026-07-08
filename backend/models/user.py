from sqlalchemy import String, Boolean, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from backend.core.database import Base
from datetime import datetime
import uuid

class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    risk_tolerance: Mapped[str] = mapped_column(String(20), default="moderate")
    capital_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    signals: Mapped[list["Signal"]] = relationship(back_populates="user")
