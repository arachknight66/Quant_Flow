from sqlalchemy import String, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from backend.core.database import Base
from datetime import datetime
import uuid, enum

class AssetType(str, enum.Enum):
    STOCK = "stock"
    CRYPTO = "crypto"
    ETF = "etf"
    INDEX = "index"

class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    asset_type: Mapped[AssetType] = mapped_column(SAEnum(AssetType), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(50))
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    last_updated: Mapped[datetime | None] = mapped_column()
    ohlcv_data: Mapped[list["OHLCVData"]] = relationship(back_populates="asset")
    signals: Mapped[list["Signal"]] = relationship(back_populates="asset")
