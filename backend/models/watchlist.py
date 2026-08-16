from sqlalchemy import Text, ForeignKey, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.core.database import Base
from datetime import datetime
import uuid

class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    asset_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    added_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="watchlist_items")
    asset: Mapped["Asset"] = relationship("Asset")
