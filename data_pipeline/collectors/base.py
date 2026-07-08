from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class OHLCVRecord:
    symbol: str
    interval: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    adj_close: Optional[float] = None

    def __post_init__(self):
        if self.high < self.low:
            raise ValueError(f"[{self.symbol} @ {self.ts}] high={self.high} < low={self.low}")
        if self.close < 0 or self.open < 0:
            raise ValueError(f"[{self.symbol} @ {self.ts}] negative price")
        if self.volume < 0:
            raise ValueError(f"[{self.symbol} @ {self.ts}] negative volume")

class BaseCollector(ABC):
    @abstractmethod
    async def fetch_historical(self, symbol: str, interval: str,
                               start: datetime, end: Optional[datetime] = None) -> list[OHLCVRecord]: ...
    @abstractmethod
    async def fetch_latest(self, symbol: str, interval: str = "1d") -> Optional[OHLCVRecord]: ...
    async def stream(self, symbols: list[str], callback):
        raise NotImplementedError(f"{self.__class__.__name__} does not support streaming.")
