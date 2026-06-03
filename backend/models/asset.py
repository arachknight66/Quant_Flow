# backend/models/asset.py
from sqlalchemy import String, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from backend.core.database import Base
from datetime import datetime
import uuid
import enum


class AssetType(str, enum.Enum):
    STOCK = "stock"
    CRYPTO = "crypto"
    ETF = "etf"
    INDEX = "index"


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    symbol: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    asset_type: Mapped[AssetType] = mapped_column(SAEnum(AssetType), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(50))
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    last_updated: Mapped[datetime | None] = mapped_column()

    # Relationships
    ohlcv_data: Mapped[list["OHLCVData"]] = relationship(back_populates="asset")
    signals: Mapped[list["Signal"]] = relationship(back_populates="asset")


# backend/models/ohlcv.py
from sqlalchemy import Index, UniqueConstraint, ForeignKey, String, Float, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from backend.core.database import Base
from datetime import datetime
import uuid


class OHLCVData(Base):
    """
    Time-series candlestick data.

    PERFORMANCE NOTE:
    This table will be the largest in the system. Index strategy:
    - Composite index on (asset_id, interval, ts DESC) for time-range queries
    - Partial index on recent data for live dashboard queries
    - Consider TimescaleDB hypertable partitioning for >10M rows

    STORAGE NOTE:
    Float32 would halve storage vs Float64 with minimal precision loss
    for price data. For now using Float (Python float = double precision)
    for correctness; optimize later with column type override.
    """
    __tablename__ = "ohlcv_data"

    # Use BigInteger PK for performance (UUID is larger, slower for sequential inserts)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    interval: Mapped[str] = mapped_column(String(10), nullable=False)
    # e.g. "1m", "5m", "1h", "1d"

    ts: Mapped[datetime] = mapped_column(nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    adj_close: Mapped[float | None] = mapped_column(Float)

    asset: Mapped["Asset"] = relationship(back_populates="ohlcv_data")

    __table_args__ = (
        # Prevents duplicate candles
        UniqueConstraint("asset_id", "interval", "ts", name="uq_ohlcv_asset_interval_ts"),
        # Primary query pattern: get all candles for an asset in a time range
        Index("ix_ohlcv_asset_interval_ts", "asset_id", "interval", "ts"),
    )