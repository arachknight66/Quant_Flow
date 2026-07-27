import httpx
import re
import json
from datetime import datetime, timezone, timedelta
from typing import Optional
import structlog
from data_pipeline.collectors.base import BaseCollector, OHLCVRecord

log = structlog.get_logger()

KNOWN_EXCHANGES = {
    "AAPL": "NASDAQ", "MSFT": "NASDAQ", "NVDA": "NASDAQ", "TSLA": "NASDAQ",
    "AMZN": "NASDAQ", "GOOGL": "NASDAQ", "META": "NASDAQ", "QQQ": "NASDAQ",
    "TLT": "NASDAQ", "JPM": "NYSE", "V": "NYSE", "JNJ": "NYSE",
    "XOM": "NYSE", "SPY": "NYSEARCA", "GLD": "NYSEARCA"
}

class GoogleFinanceCollector(BaseCollector):
    """
    Data collector that fetches real-time quotes and historical price bars from Google Finance.
    Implements the BaseCollector interface.
    """
    def __init__(self):
        self.base_url = "https://www.google.com/finance/quote"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _format_google_symbol(self, symbol: str) -> str:
        s = symbol.upper().strip()
        if ":" in s or "-" in s:
            return s
        exchange = KNOWN_EXCHANGES.get(s, "NASDAQ")
        return f"{s}:{exchange}"

    async def fetch_historical(self, symbol: str, interval: str,
                               start: datetime, end: Optional[datetime] = None) -> list[OHLCVRecord]:
        gf_symbol = self._format_google_symbol(symbol)
        url = f"{self.base_url}/{gf_symbol}"
        
        if end is None:
            end = datetime.now(timezone.utc)

        async with httpx.AsyncClient(follow_redirects=True) as client:
            try:
                resp = await client.get(url, headers=self.headers, timeout=15.0)
                resp.raise_for_status()
                html = resp.text
            except Exception as e:
                log.error("Failed to fetch Google Finance page", symbol=symbol, error=str(e))
                raise RuntimeError(f"Google Finance fetch error: {e}")

        records = []
        
        # 1. Parse historical candles embedded in AF_initDataCallback
        callbacks = re.findall(r'AF_initDataCallback\((\{.*?\}\));</script>', html, re.DOTALL)
        for cb in callbacks:
            if any(k in cb for k in ["ds:12", "ds:13", "ds:10", "ds:11"]):
                data_match = re.search(r'data:\s*(\[.*\]),\s*sideChannel', cb, re.DOTALL)
                if data_match:
                    try:
                        raw_arr = json.loads(data_match.group(1))
                        series_list = self._extract_series(raw_arr)
                        for bar in series_list:
                            if len(bar) >= 5:
                                ts = bar[0]
                                if isinstance(ts, (int, float)):
                                    dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
                                elif isinstance(ts, str):
                                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                                else:
                                    continue
                                
                                if dt < start or dt > end:
                                    continue

                                close_p = float(bar[1])
                                open_p = float(bar[2]) if len(bar) > 2 and bar[2] else close_p
                                high_p = float(bar[3]) if len(bar) > 3 and bar[3] else max(open_p, close_p)
                                low_p  = float(bar[4]) if len(bar) > 4 and bar[4] else min(open_p, close_p)
                                vol    = float(bar[5]) if len(bar) > 5 and bar[5] else 0.0

                                records.append(OHLCVRecord(
                                    symbol=symbol,
                                    interval=interval,
                                    ts=dt,
                                    open=open_p,
                                    high=high_p,
                                    low=low_p,
                                    close=close_p,
                                    volume=vol,
                                    adj_close=close_p
                                ))
                    except Exception as ex:
                        log.debug("Skipped unparseable callback block", error=str(ex))

        # 2. Fallback: Parse live quote bar if historical series was unavailable in callbacks
        if not records:
            latest = await self._parse_live_quote(html, symbol, interval)
            if latest:
                records.append(latest)

        records.sort(key=lambda r: r.ts)
        return records

    def _extract_series(self, data: list) -> list:
        series = []

        def _search(obj):
            if isinstance(obj, list):
                if len(obj) >= 4 and isinstance(obj[0], (int, float, str)) and isinstance(obj[1], (int, float)):
                    series.append(obj)
                else:
                    for item in obj:
                        _search(item)
            elif isinstance(obj, dict):
                for v in obj.values():
                    _search(v)

        _search(data)
        return series

    async def _parse_live_quote(self, html: str, symbol: str, interval: str) -> Optional[OHLCVRecord]:
        try:
            price_match = re.search(r'data-last-price="([0-9\.]+)"', html)
            if not price_match:
                dollar_matches = re.findall(r'>\$([0-9,]+\.[0-9]{2})<', html)
                if not dollar_matches:
                    return None
                current_price = float(dollar_matches[0].replace(",", ""))
                open_price = float(dollar_matches[1].replace(",", "")) if len(dollar_matches) > 1 else current_price
                high_price = float(dollar_matches[2].replace(",", "")) if len(dollar_matches) > 2 else max(current_price, open_price)
                low_price  = float(dollar_matches[3].replace(",", "")) if len(dollar_matches) > 3 else min(current_price, open_price)
            else:
                current_price = float(price_match.group(1))
                open_price = current_price
                high_price = current_price
                low_price  = current_price

            now = datetime.now(timezone.utc)
            return OHLCVRecord(
                symbol=symbol,
                interval=interval,
                ts=now,
                open=open_price,
                high=max(high_price, current_price, open_price),
                low=min(low_price, current_price, open_price),
                close=current_price,
                volume=0.0,
                adj_close=current_price
            )
        except Exception as e:
            log.warning("Failed to parse live quote from Google Finance HTML", symbol=symbol, error=str(e))
            return None

    async def fetch_latest(self, symbol: str, interval: str = "1d") -> Optional[OHLCVRecord]:
        start = datetime.now(timezone.utc) - timedelta(days=5)
        records = await self.fetch_historical(symbol, interval, start=start)
        return records[-1] if records else None
