# data_pipeline/validators/ohlcv_validator.py
"""
Data quality validation for OHLCV data.

In financial ML, data quality is MORE important than model sophistication.
Garbage in, garbage out — but worse: garbage in causes subtly wrong
signals that are hard to detect until you've lost money.
"""
import pandas as pd
import numpy as np
import structlog
from typing import Optional

log = structlog.get_logger()


class DataQualityError(Exception):
    """Raised when data quality checks fail critically."""
    pass


def validate_ohlcv_dataframe(
    df: pd.DataFrame,
    symbol: str,
    max_missing_pct: float = 0.05,  # Fail if >5% missing
    max_zero_volume_pct: float = 0.20,  # Warn if >20% zero volume
) -> pd.DataFrame:
    """
    Validate and clean an OHLCV DataFrame.

    Checks performed:
    1. Required columns present
    2. No negative prices (obvious data error)
    3. OHLCV relationship integrity (high >= low, high >= open, etc.)
    4. Extreme outlier detection (>10x median price = suspect)
    5. Missing value handling
    6. Duplicate timestamp removal
    7. Chronological ordering

    Returns cleaned DataFrame with issues logged.
    Raises DataQualityError for critical failures.
    """
    if df.empty:
        return df

    required_cols = {"Open", "High", "Low", "Close"}
    missing_cols = required_cols - set(df.columns)
    if missing_cols:
        raise DataQualityError(f"{symbol}: Missing columns {missing_cols}")

    original_len = len(df)
    issues = []

    # ---- 1. Remove duplicate timestamps ----
    before = len(df)
    df = df[~df.index.duplicated(keep="last")]
    if len(df) < before:
        issues.append(f"Removed {before - len(df)} duplicate timestamps")

    # ---- 2. Sort chronologically ----
    df = df.sort_index()

    # ---- 3. Check for negative prices ----
    price_cols = ["Open", "High", "Low", "Close"]
    neg_prices = (df[price_cols] < 0).any(axis=1).sum()
    if neg_prices > 0:
        log.warning("Negative prices found", symbol=symbol, count=int(neg_prices))
        df = df[(df[price_cols] >= 0).all(axis=1)]
        issues.append(f"Removed {neg_prices} rows with negative prices")

    # ---- 4. OHLCV integrity checks ----
    # High should be >= Open, Close, Low
    integrity_violations = (
        (df["High"] < df["Low"]) |
        (df["High"] < df["Open"]) |
        (df["High"] < df["Close"]) |
        (df["Low"] > df["Open"]) |
        (df["Low"] > df["Close"])
    )
    n_violations = integrity_violations.sum()
    if n_violations > 0:
        log.warning("OHLCV integrity violations", symbol=symbol, count=int(n_violations))
        df = df[~integrity_violations]
        issues.append(f"Removed {n_violations} OHLCV integrity violations")

    # ---- 5. Extreme outlier detection ----
    # A price 10x the rolling median is almost certainly a data error
    rolling_median = df["Close"].rolling(20, min_periods=1).median()
    extreme_prices = df["Close"] > (rolling_median * 10)
    n_extreme = extreme_prices.sum()
    if n_extreme > 0:
        # Don't remove automatically — log and flag for review
        # Could be legitimate (penny stock went 10x, split adjusted error)
        log.warning(
            "Extreme price outliers detected",
            symbol=symbol,
            count=int(n_extreme),
            message="Manual review recommended"
        )

    # ---- 6. Missing value handling ----
    missing_pct = df[price_cols].isnull().mean().max()
    if missing_pct > max_missing_pct:
        raise DataQualityError(
            f"{symbol}: {missing_pct:.1%} missing values exceeds threshold {max_missing_pct:.1%}"
        )

    # Forward-fill small gaps (e.g. weekends, holidays)
    # Only fill up to 3 consecutive NaN values
    df[price_cols] = df[price_cols].ffill(limit=3)

    # ---- 7. Volume checks ----
    if "Volume" in df.columns:
        zero_vol_pct = (df["Volume"] == 0).mean()
        if zero_vol_pct > max_zero_volume_pct:
            log.warning(
                "High proportion of zero-volume candles",
                symbol=symbol,
                pct=f"{zero_vol_pct:.1%}",
                message="Possible illiquid asset or data issue"
            )

    # ---- Final summary ----
    final_len = len(df)
    if issues:
        log.info(
            "Data quality issues resolved",
            symbol=symbol,
            original_rows=original_len,
            final_rows=final_len,
            issues=issues
        )

    return df