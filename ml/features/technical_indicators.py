# ml/features/technical_indicators.py
"""
Technical indicator computation.

IMPORTANT METHODOLOGICAL NOTE:
All indicators must be computed WITHOUT lookahead bias.
This means:
- At time t, only use data from t and earlier
- Rolling windows must use closed='left' or shift appropriately
- Any 'future' information (e.g. next day's price) is TARGET, not feature

NORMALISATION:
Raw indicator values are not ML-ready. We compute both:
- Raw values (for display in UI)
- Z-score normalised versions (for ML features)
- Rank-normalised versions (for robustness to outliers)
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional
import warnings

warnings.filterwarnings("ignore", category=RuntimeWarning)


@dataclass
class IndicatorConfig:
    """Centralised configuration for all indicator parameters."""
    # RSI
    rsi_period: int = 14
    # MACD
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    # Bollinger Bands
    bb_period: int = 20
    bb_std: float = 2.0
    # ATR
    atr_period: int = 14
    # EMA/SMA
    ema_periods: list[int] = None
    sma_periods: list[int] = None
    # Momentum
    momentum_period: int = 10
    roc_period: int = 10
    # Volatility
    volatility_period: int = 20
    # Z-score normalisation window
    zscore_window: int = 252  # 1 trading year

    def __post_init__(self):
        if self.ema_periods is None:
            self.ema_periods = [9, 21, 50, 200]
        if self.sma_periods is None:
            self.sma_periods = [20, 50, 200]


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """
    Relative Strength Index (Wilder's RSI).

    Formula:
        RSI = 100 - 100 / (1 + RS)
        RS = Avg(Up moves over period) / Avg(Down moves over period)

    Uses Wilder's smoothed moving average, NOT simple average.
    The first value uses simple average; subsequent values use SMMA.

    Interpretation:
        > 70: Potentially overbought (but can stay overbought in trends!)
        < 30: Potentially oversold
        50: Neutral momentum level

    ML Feature Design:
        - Raw RSI is NOT stationary — use RSI change or RSI-50 deviation
        - RSI divergence from price can be informative
        - Don't use RSI as a standalone signal
    """
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    # Wilder's smoothed MA (equivalent to EMA with alpha=1/period)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    return rsi.rename("rsi")


def compute_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """
    Moving Average Convergence Divergence.

    Components:
        MACD Line = EMA(fast) - EMA(slow)
        Signal Line = EMA(MACD Line, signal)
        Histogram = MACD Line - Signal Line

    ML Feature Design:
        - Histogram is the most informative: measures momentum acceleration
        - MACD crossing signal line is a traditional signal (but noisy alone)
        - Normalise histogram by price level for cross-asset comparison
    """
    ema_fast = close.ewm(span=fast, min_periods=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, min_periods=slow, adjust=False).mean()

    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, min_periods=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    return pd.DataFrame({
        "macd": macd_line,
        "macd_signal": signal_line,
        "macd_hist": histogram,
        # Normalise histogram as fraction of current price for comparability
        "macd_hist_pct": histogram / close,
    })


def compute_bollinger_bands(
    close: pd.Series,
    period: int = 20,
    n_std: float = 2.0,
) -> pd.DataFrame:
    """
    Bollinger Bands — volatility envelope around a moving average.

    Components:
        Middle Band = SMA(period)
        Upper Band = Middle + n_std * rolling_std(period)
        Lower Band = Middle - n_std * rolling_std(period)
        %B = (Price - Lower) / (Upper - Lower)  ← position within bands
        Width = (Upper - Lower) / Middle          ← normalised band width

    ML Feature Design:
        - %B is bounded [0, 1] in normal conditions — good ML feature
        - Band Width measures volatility regime — critical for regime features
        - Band squeeze (low width) often precedes breakout (high width)
    """
    rolling = close.rolling(period)
    middle = rolling.mean()
    std = rolling.std(ddof=1)  # Sample std (ddof=1 is standard)

    upper = middle + (n_std * std)
    lower = middle - (n_std * std)

    band_width = (upper - lower) / middle
    percent_b = (close - lower) / (upper - lower)

    return pd.DataFrame({
        "bb_upper": upper,
        "bb_middle": middle,
        "bb_lower": lower,
        "bb_width": band_width,
        "bb_pct_b": percent_b,
    })


def compute_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """
    Average True Range — measures market volatility.

    True Range = max(
        High - Low,
        |High - Previous Close|,
        |Low - Previous Close|
    )
    ATR = Wilder's SMMA(True Range, period)

    Critical for:
        - Position sizing (volatility-adjusted position size)
        - Stop-loss placement (e.g. 2-ATR trailing stop)
        - Regime classification (high vs low volatility)

    ML Feature Design:
        - ATR/Close = normalised volatility (use this, not raw ATR)
        - Rolling percentile of ATR identifies volatility regimes
    """
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    return atr.rename("atr")


def compute_vwap(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
) -> pd.Series:
    """
    Volume Weighted Average Price.

    VWAP = Σ(Typical Price × Volume) / Σ(Volume)
    Typical Price = (High + Low + Close) / 3

    Standard VWAP resets daily (intraday use).
    For daily data, we use rolling VWAP (not standard but useful as ML feature).

    Significance:
        - Institutional benchmark — algos buy below VWAP, sell above
        - Price above VWAP = bullish intraday context
        - Price/VWAP deviation is a mean-reversion signal

    ML Feature Design:
        - (Price - VWAP) / VWAP = signed normalised deviation (good feature)
    """
    typical_price = (high + low + close) / 3
    tp_volume = typical_price * volume
    vwap = tp_volume.rolling(20).sum() / volume.rolling(20).sum()

    return vwap.rename("vwap")


def compute_log_returns(close: pd.Series, periods: list[int] = None) -> pd.DataFrame:
    """
    Log returns at multiple horizons.

    log_return(t, n) = ln(P_t / P_{t-n})

    Why log returns instead of simple returns:
    1. Additively composable: daily log return sum = total log return
    2. Approximately normally distributed (central limit theorem applies)
    3. Bounded from below: -∞ to +∞ (but practical range is -1 to 1)
    4. Numerically stable for small changes

    Critical ML point: log returns are more stationary than prices.
    Always test for stationarity (ADF test) before including in model.
    """
    if periods is None:
        periods = [1, 2, 3, 5, 10, 20]

    result = {}
    for p in periods:
        result[f"log_return_{p}d"] = np.log(close / close.shift(p))

    return pd.DataFrame(result)


def compute_rolling_volatility(
    close: pd.Series,
    periods: list[int] = None,
    annualise: bool = True,
    trading_days: int = 252,
) -> pd.DataFrame:
    """
    Rolling historical volatility.

    σ_t = std(log_returns over window) × √(trading_days)  [annualised]

    Key insight: Volatility is itself predictable (unlike returns).
    GARCH effects mean high volatility clusters — use lagged volatility
    as a feature.

    ML Feature Design:
        - Vol ratio: current_vol / long_term_vol (regime indicator)
        - Vol percentile: rank in historical distribution
        - Vol of vol: second-order volatility measure
    """
    if periods is None:
        periods = [5, 10, 20, 60]

    log_returns = np.log(close / close.shift(1))
    result = {}

    for p in periods:
        vol = log_returns.rolling(p).std()
        if annualise:
            vol = vol * np.sqrt(trading_days)
        result[f"vol_{p}d"] = vol

    # Volatility ratio (current vol vs long-term context)
    if 20 in periods and 60 in periods:
        result["vol_ratio_20_60"] = result["vol_20d"] / result["vol_60d"]

    return pd.DataFrame(result)


def compute_zscore(series: pd.Series, window: int = 252) -> pd.Series:
    """
    Rolling Z-score normalisation.

    z_t = (x_t - μ_{t-window:t}) / σ_{t-window:t}

    Why z-score for ML features?
    - Removes level effects (a stock at $5 vs $500)
    - Captures deviation from historical norm
    - Bounded: most values fall in [-3, +3]
    - Stationary when computed from stationary inputs

    WARNING: Do not z-score raw prices — prices are not stationary.
    Z-score indicators (RSI, vol, log returns) which are already more stationary.
    """
    rolling = series.rolling(window, min_periods=max(window // 4, 10))
    return ((series - rolling.mean()) / rolling.std()).rename(f"{series.name}_zscore")


def build_feature_matrix(
    df: pd.DataFrame,
    config: Optional[IndicatorConfig] = None,
    drop_na: bool = True,
) -> pd.DataFrame:
    """
    Main entry point: compute all features for a given OHLCV DataFrame.

    Input: DataFrame with columns Open, High, Low, Close, Volume
    Output: DataFrame with all computed features

    The returned features are:
    - Display features (raw values, for UI charts)
    - ML features (normalised, for model input)
    - Target variable (for training — NOT included in production inference)

    CRITICAL: The caller is responsible for ensuring:
    - No data after the prediction timestamp is used
    - Features are computed BEFORE target is known
    """
    if config is None:
        config = IndicatorConfig()

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df.get("Volume", pd.Series(np.nan, index=df.index, name="Volume"))

    features = pd.DataFrame(index=df.index)

    # ---- Price features ----
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df:
            features[col] = df[col]

    # ---- Log returns (multiple horizons) ----
    returns = compute_log_returns(close, periods=[1, 2, 3, 5, 10, 20])
    features = pd.concat([features, returns], axis=1)

    # ---- RSI ----
    features["rsi"] = compute_rsi(close, config.rsi_period)
    features["rsi_change"] = features["rsi"].diff()
    features["rsi_zscore"] = compute_zscore(features["rsi"])

    # ---- MACD ----
    macd_df = compute_macd(close, config.macd_fast, config.macd_slow, config.macd_signal)
    features = pd.concat([features, macd_df], axis=1)

    # ---- Bollinger Bands ----
    bb_df = compute_bollinger_bands(close, config.bb_period, config.bb_std)
    features = pd.concat([features, bb_df], axis=1)

    # ---- ATR ----
    features["atr"] = compute_atr(high, low, close, config.atr_period)
    features["atr_pct"] = features["atr"] / close  # normalised ATR

    # ---- VWAP (if volume available) ----
    if "Volume" in df and not df["Volume"].isna().all():
        features["vwap"] = compute_vwap(high, low, close, volume)
        features["price_vwap_deviation"] = (close - features["vwap"]) / features["vwap"]

    # ---- EMAs ----
    for period in config.ema_periods:
        ema = close.ewm(span=period, min_periods=period, adjust=False).mean()
        features[f"ema_{period}"] = ema
        features[f"price_ema_{period}_ratio"] = close / ema  # price relative to EMA

    # ---- SMAs ----
    for period in config.sma_periods:
        sma = close.rolling(period, min_periods=period).mean()
        features[f"sma_{period}"] = sma
        features[f"price_sma_{period}_ratio"] = close / sma

    # ---- Moving average crossovers (binary features) ----
    if 50 in config.sma_periods and 200 in config.sma_periods:
        features["golden_cross"] = (features["sma_50"] > features["sma_200"]).astype(int)

    # ---- Rolling volatility ----
    vol_df = compute_rolling_volatility(close)
    features = pd.concat([features, vol_df], axis=1)

    # ---- Momentum / ROC ----
    features[f"momentum_{config.momentum_period}"] = (
        close / close.shift(config.momentum_period) - 1
    )
    features["roc"] = close.pct_change(config.roc_period)

    # ---- Volume features ----
    if "Volume" in df:
        features["volume_sma_20"] = volume.rolling(20).mean()
        features["volume_ratio"] = volume / features["volume_sma_20"]
        features["volume_zscore"] = compute_zscore(volume)
        # On-Balance Volume (simplified)
        obv = (np.sign(close.diff()) * volume).fillna(0).cumsum()
        features["obv_zscore"] = compute_zscore(obv)

    # ---- Z-score key indicators ----
    for col in ["roc", f"momentum_{config.momentum_period}", "bb_pct_b"]:
        if col in features:
            features[f"{col}_zscore"] = compute_zscore(features[col])

    # ---- Drop rows with NaN (from indicator warmup period) ----
    if drop_na:
        pre_len = len(features)
        features = features.dropna()
        dropped = pre_len - len(features)
        if dropped > 0:
            pass  # Normal — indicator warmup requires this

    return features