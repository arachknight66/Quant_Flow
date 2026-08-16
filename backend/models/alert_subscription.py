from sqlalchemy import Boolean, ForeignKey, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.core.database import Base
from datetime import datetime
import uuid

class AlertSubscription(Base):
    __tablename__ = "alert_subscriptions"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    asset_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="alert_subscriptions")
    asset: Mapped["Asset"] = relationship("Asset")
