from sqlalchemy import String, Float, ForeignKey, JSON, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.core.database import Base
from datetime import datetime
import uuid

class Signal(Base):
    __tablename__ = "signals"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    asset_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("assets.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    prob_profit: Mapped[float | None] = mapped_column(Float)
    kelly_fraction: Mapped[float | None] = mapped_column(Float)
    suggested_allocation: Mapped[float | None] = mapped_column(Float)
    expected_return_lo: Mapped[float | None] = mapped_column(Float)
    expected_return_hi: Mapped[float | None] = mapped_column(Float)
    var_95: Mapped[float | None] = mapped_column(Float)
    sharpe_est: Mapped[float | None] = mapped_column(Float)
    features_snapshot: Mapped[dict | None] = mapped_column(JSON)
    model_version: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    resolved: Mapped[bool] = mapped_column(default=False)
    outcome_correct: Mapped[bool | None] = mapped_column(default=None)
    actual_return_pct: Mapped[float | None] = mapped_column(Float, default=None)
    user: Mapped["User"] = relationship("User", back_populates="signals")
    asset: Mapped["Asset"] = relationship("Asset", back_populates="signals")
