# backend/models/signal.py
"""
Signal ORM model.

CRITICAL FIX: backend/models/user.py declares
    signals: Mapped[list["Signal"]] = relationship(back_populates="user")
but this Signal class was never defined anywhere in the codebase.
SQLAlchemy resolves string-quoted type hints lazily at first mapper
configuration (i.e. at app startup, not at import time of user.py),
so the failure mode is a late, confusing
    sqlalchemy.exc.InvalidRequestError: When initializing mapper ...
    could not locate a class named 'Signal'
This file is what that forward reference resolves to.
"""
from sqlalchemy import String, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from backend.core.database import Base
from datetime import datetime
import uuid


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("assets.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    prob_profit: Mapped[float | None] = mapped_column(Float)
    kelly_fraction: Mapped[float | None] = mapped_column(Float)
    suggested_allocation: Mapped[float | None] = mapped_column(Float)
    expected_return_lo: Mapped[float | None] = mapped_column(Float)
    expected_return_hi: Mapped[float | None] = mapped_column(Float)
    var_95: Mapped[float | None] = mapped_column(Float)
    sharpe_est: Mapped[float | None] = mapped_column(Float)
    # Stores the full ML feature vector at prediction time for reproducibility.
    # Can be 60+ floats per signal (see XGBoostSignalModel.predict() feature_snapshot) —
    # this is intentional, it's what lets you debug why a model made a specific call.
    features_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    model_version: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="signals")
    asset: Mapped["Asset"] = relationship(back_populates="signals")