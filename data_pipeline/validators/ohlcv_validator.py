import pandas as pd
import numpy as np
import structlog
from typing import Optional

log = structlog.get_logger()

class DataQualityError(Exception):
    pass

def validate_ohlcv_dataframe(df: pd.DataFrame, symbol: str,
                              max_missing_pct: float = 0.05,
                              max_zero_volume_pct: float = 0.20) -> pd.DataFrame:
    if df.empty:
        return df
    required_cols = {"Open", "High", "Low", "Close"}
    missing_cols = required_cols - set(df.columns)
    if missing_cols:
        raise DataQualityError(f"{symbol}: Missing columns {missing_cols}")

    original_len = len(df)
    issues = []

    before = len(df)
    df = df[~df.index.duplicated(keep="last")]
    if len(df) < before:
        issues.append(f"Removed {before - len(df)} duplicate timestamps")

    df = df.sort_index()

    price_cols = ["Open", "High", "Low", "Close"]
    neg = (df[price_cols] < 0).any(axis=1).sum()
    if neg > 0:
        log.warning("Negative prices found", symbol=symbol, count=int(neg))
        df = df[(df[price_cols] >= 0).all(axis=1)]
        issues.append(f"Removed {neg} rows with negative prices")

    violations = (
        (df["High"] < df["Low"]) | (df["High"] < df["Open"]) |
        (df["High"] < df["Close"]) | (df["Low"] > df["Open"]) | (df["Low"] > df["Close"])
    )
    n_v = violations.sum()
    if n_v > 0:
        log.warning("OHLCV integrity violations", symbol=symbol, count=int(n_v))
        df = df[~violations]
        issues.append(f"Removed {n_v} OHLCV integrity violations")

    missing_pct = df[price_cols].isnull().mean().max()
    if missing_pct > max_missing_pct:
        raise DataQualityError(
            f"{symbol}: {missing_pct:.1%} missing values exceeds threshold {max_missing_pct:.1%}")

    df[price_cols] = df[price_cols].ffill(limit=3)

    if "Volume" in df.columns:
        zero_vol_pct = (df["Volume"] == 0).mean()
        if zero_vol_pct > max_zero_volume_pct:
            log.warning("High proportion of zero-volume candles", symbol=symbol,
                        pct=f"{zero_vol_pct:.1%}")

    if issues:
        log.info("Data quality issues resolved", symbol=symbol,
                 original_rows=original_len, final_rows=len(df), issues=issues)
    return df
