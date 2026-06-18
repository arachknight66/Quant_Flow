# data_pipeline/collectors/base.py
"""
Abstract base class for all data collectors.
Every collector (yfinance, ccxt, Alpha Vantage) implements this interface.
This enforces a consistent contract regardless of data source.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class OHLCVRecord:
    """
    Canonical internal representation of a single OHLCV candle.
    All collectors convert their source format into this.
    """
    symbol: str
    interval: str
    ts: datetime          # UTC timestamp of candle open
    open: float
    high: float
    low: float
    close: float
    volume: float
    adj_close: Optional[float] = None

    def __post_init__(self):
        # Defensive validation — catch collector bugs early
        if self.high < self.low:
            raise ValueError(
                f"[{self.symbol} @ {self.ts}] high={self.high} < low={self.low}"
            )
        if self.close < 0 or self.open < 0:
            raise ValueError(
                f"[{self.symbol} @ {self.ts}] negative price: "
                f"open={self.open}, close={self.close}"
            )
        if self.volume < 0:
            raise ValueError(
                f"[{self.symbol} @ {self.ts}] negative volume: {self.volume}"
            )


class BaseCollector(ABC):
    """
    Abstract interface for market data collectors.

    All concrete collectors must implement:
      - fetch_historical: bulk historical OHLCV
      - fetch_latest: single most-recent candle

    Optional override:
      - stream: real-time tick stream (for WebSocket-capable sources)
    """

    @abstractmethod
    async def fetch_historical(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: Optional[datetime] = None,
    ) -> list[OHLCVRecord]:
        """
        Fetch historical OHLCV bars for a symbol.

        Args:
            symbol:   Ticker (e.g. "AAPL", "BTC-USD")
            interval: Bar size (e.g. "1d", "1h", "5m")
            start:    Start datetime (UTC, inclusive)
            end:      End datetime (UTC, inclusive). Defaults to now.

        Returns:
            List of OHLCVRecord, sorted ascending by ts.
            Empty list if no data available (not an error).

        Raises:
            ValueError:   Invalid symbol or interval
            RuntimeError: Network or API failure after retries
        """
        ...

    @abstractmethod
    async def fetch_latest(
        self,
        symbol: str,
        interval: str = "1d",
    ) -> Optional[OHLCVRecord]:
        """
        Fetch the single most recent completed candle.

        Returns None if no data available.
        """
        ...

    async def stream(self, symbols: list[str], callback):
        """
        Optional: stream real-time ticks.
        Default implementation raises NotImplementedError.
        Override in collectors that support WebSocket feeds.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support streaming. "
            "Use a WebSocket-capable collector (e.g. BinanceCollector)."
        )