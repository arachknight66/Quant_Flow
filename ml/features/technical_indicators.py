import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional
import warnings
warnings.filterwarnings("ignore", category=RuntimeWarning)

@dataclass
class IndicatorConfig:
    rsi_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bb_period: int = 20
    bb_std: float = 2.0
    atr_period: int = 14
    ema_periods: list = None
    sma_periods: list = None
    momentum_period: int = 10
    roc_period: int = 10
    zscore_window: int = 252
    def __post_init__(self):
        if self.ema_periods is None: self.ema_periods = [9, 21, 50, 200]
        if self.sma_periods is None: self.sma_periods = [20, 50, 200]

def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs  = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.rename("rsi")

def compute_macd(close, fast=12, slow=26, signal=9):
    ema_fast   = close.ewm(span=fast, min_periods=fast, adjust=False).mean()
    ema_slow   = close.ewm(span=slow, min_periods=slow, adjust=False).mean()
    macd_line  = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, min_periods=signal, adjust=False).mean()
    histogram  = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "macd_signal": signal_line,
                          "macd_hist": histogram, "macd_hist_pct": histogram / close})

def compute_bollinger_bands(close, period=20, n_std=2.0):
    rolling = close.rolling(period)
    middle  = rolling.mean()
    std     = rolling.std(ddof=1)
    upper   = middle + n_std * std
    lower   = middle - n_std * std
    return pd.DataFrame({"bb_upper": upper, "bb_middle": middle, "bb_lower": lower,
                          "bb_width": (upper - lower) / middle,
                          "bb_pct_b": (close - lower) / (upper - lower)})

def compute_atr(high, low, close, period=14):
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(),
                    (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean().rename("atr")

def compute_vwap(high, low, close, volume):
    tp = (high + low + close) / 3
    return (tp * volume).rolling(20).sum() / volume.rolling(20).sum()

def compute_log_returns(close, periods=None):
    if periods is None: periods = [1, 2, 3, 5, 10, 20]
    return pd.DataFrame({f"log_return_{p}d": np.log(close / close.shift(p)) for p in periods})

def compute_rolling_volatility(close, periods=None, annualise=True, trading_days=252):
    if periods is None: periods = [5, 10, 20, 60]
    log_returns = np.log(close / close.shift(1))
    result = {}
    for p in periods:
        vol = log_returns.rolling(p).std()
        result[f"vol_{p}d"] = vol * np.sqrt(trading_days) if annualise else vol
    if 20 in periods and 60 in periods:
        result["vol_ratio_20_60"] = result["vol_20d"] / result["vol_60d"]
    return pd.DataFrame(result)

def compute_zscore(series: pd.Series, window: int = 252) -> pd.Series:
    rolling = series.rolling(window, min_periods=max(window // 4, 10))
    return ((series - rolling.mean()) / rolling.std()).rename(f"{series.name}_zscore")

def build_feature_matrix(df: pd.DataFrame, config=None, drop_na: bool = True) -> pd.DataFrame:
    if config is None: config = IndicatorConfig()
    close  = df["Close"]
    high   = df["High"]
    low    = df["Low"]
    volume = df.get("Volume", pd.Series(np.nan, index=df.index, name="Volume"))
    features = pd.DataFrame(index=df.index)
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df: features[col] = df[col]
    features = pd.concat([features, compute_log_returns(close)], axis=1)
    features["rsi"]        = compute_rsi(close, config.rsi_period)
    features["rsi_change"] = features["rsi"].diff()
    features["rsi_zscore"] = compute_zscore(features["rsi"])
    features = pd.concat([features, compute_macd(close, config.macd_fast,
                          config.macd_slow, config.macd_signal)], axis=1)
    features = pd.concat([features, compute_bollinger_bands(close,
                          config.bb_period, config.bb_std)], axis=1)
    features["atr"]     = compute_atr(high, low, close, config.atr_period)
    features["atr_pct"] = features["atr"] / close
    if "Volume" in df and not df["Volume"].isna().all():
        features["vwap"] = compute_vwap(high, low, close, volume)
        features["price_vwap_deviation"] = (close - features["vwap"]) / features["vwap"]
    for p in config.ema_periods:
        ema = close.ewm(span=p, min_periods=p, adjust=False).mean()
        features[f"ema_{p}"] = ema
        features[f"price_ema_{p}_ratio"] = close / ema
    for p in config.sma_periods:
        sma = close.rolling(p, min_periods=p).mean()
        features[f"sma_{p}"] = sma
        features[f"price_sma_{p}_ratio"] = close / sma
    if 50 in config.sma_periods and 200 in config.sma_periods:
        features["golden_cross"] = (features["sma_50"] > features["sma_200"]).astype(int)
    features = pd.concat([features, compute_rolling_volatility(close)], axis=1)
    features[f"momentum_{config.momentum_period}"] = close / close.shift(config.momentum_period) - 1
    features["roc"] = close.pct_change(config.roc_period)
    if "Volume" in df:
        features["volume_sma_20"] = volume.rolling(20).mean()
        features["volume_ratio"]  = volume / features["volume_sma_20"]
        features["volume_zscore"] = compute_zscore(volume)
        obv = (np.sign(close.diff()) * volume).fillna(0).cumsum()
        features["obv_zscore"] = compute_zscore(obv)
    for col in ["roc", f"momentum_{config.momentum_period}", "bb_pct_b"]:
        if col in features:
            features[f"{col}_zscore"] = compute_zscore(features[col])
    if drop_na:
        features = features.dropna()
    return features
