from sqlalchemy import Index, UniqueConstraint, ForeignKey, String, Float, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from backend.core.database import Base
from datetime import datetime
import uuid

class OHLCVData(Base):
    __tablename__ = "ohlcv_data"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    interval: Mapped[str] = mapped_column(String(10), nullable=False)
    ts: Mapped[datetime] = mapped_column(nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    adj_close: Mapped[float | None] = mapped_column(Float)
    asset: Mapped["Asset"] = relationship("Asset", back_populates="ohlcv_data")
    __table_args__ = (
        UniqueConstraint("asset_id", "interval", "ts", name="uq_ohlcv_asset_interval_ts"),
        Index("ix_ohlcv_asset_interval_ts", "asset_id", "interval", "ts"),
    )
