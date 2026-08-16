from sqlalchemy import String, Boolean, Float, Text, ForeignKey, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.core.database import Base
from datetime import datetime
import uuid

class PortfolioPosition(Base):
    __tablename__ = "portfolio_positions"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    asset_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("assets.id"), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    avg_entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    open_date: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    close_date: Mapped[datetime | None] = mapped_column(nullable=True)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("signals.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship("User")
    asset: Mapped["Asset"] = relationship("Asset")
