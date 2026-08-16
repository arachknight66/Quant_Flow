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
    
    # Feature gates for Step 2
    enable_market_features: bool = False  # 2a
    enable_long_memory: bool = False      # 2b
    enable_vol_price: bool = False        # 2c
    enable_calendar: bool = False         # 2d

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

def build_feature_matrix(df: pd.DataFrame, config=None, drop_na: bool = True, symbol: Optional[str] = None) -> pd.DataFrame:
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

    # 2a. Cross-asset / market-wide features
    if config.enable_market_features:
        try:
            import yfinance as yf
            start_date = df.index[0]
            end_date = df.index[-1]
            
            # Fetch SPY
            spy = yf.download("SPY", start=start_date, end=end_date, interval="1d", auto_adjust=True, progress=False)
            if isinstance(spy.columns, pd.MultiIndex):
                spy.columns = spy.columns.get_level_values(0)
            spy_close = spy["Close"]
            spy_ret = np.log(spy_close / spy_close.shift(1)).rename("market_spy_return_1d")
            spy_rsi = compute_rsi(spy_close, period=14).rename("market_spy_rsi")
            
            features = features.join(spy_ret.reindex(df.index).ffill())
            features = features.join(spy_rsi.reindex(df.index).ffill())
            
            # Fetch VIX
            vix = yf.download("^VIX", start=start_date, end=end_date, interval="1d", auto_adjust=True, progress=False)
            if isinstance(vix.columns, pd.MultiIndex):
                vix.columns = vix.columns.get_level_values(0)
            vix_close = vix["Close"].rename("market_vix_level")
            vix_roc = vix["Close"].pct_change(1).rename("market_vix_roc_1d")
            
            features = features.join(vix_close.reindex(df.index).ffill())
            features = features.join(vix_roc.reindex(df.index).ffill())
            
            # Sector ETF relative strength
            SECTOR_ETFS = {
                "AAPL": "XLK", "MSFT": "XLK", "NVDA": "XLK", "AMZN": "XLY", "GOOGL": "XLK", "META": "XLK", "ADBE": "XLK", "AMD": "XLK", "CRM": "XLK",
                "JPM": "XLF", "V": "XLF", "MA": "XLF", "BAC": "XLF",
                "XOM": "XLE", "CVX": "XLE",
                "TSLA": "XLY", "WMT": "XLP", "PG": "XLP", "KO": "XLP", "PEP": "XLP", "COST": "XLP",
                "UNH": "XLV", "JNJ": "XLV", "LLY": "XLV", "MRK": "XLV",
                "RUN": "ICLN"
            }
            sym = symbol.upper() if symbol else "SPY"
            sector_etf = SECTOR_ETFS.get(sym, "SPY")
            
            if sector_etf != sym:
                etf_df = yf.download(sector_etf, start=start_date, end=end_date, interval="1d", auto_adjust=True, progress=False)
                if isinstance(etf_df.columns, pd.MultiIndex):
                    etf_df.columns = etf_df.columns.get_level_values(0)
                etf_close = etf_df["Close"]
                etf_ret = np.log(etf_close / etf_close.shift(1))
                stock_ret = np.log(close / close.shift(1))
                rel_strength_1d = (stock_ret - etf_ret).rename("market_sector_rel_strength_1d")
                
                stock_ret_5 = np.log(close / close.shift(5))
                etf_ret_5 = np.log(etf_close / etf_close.shift(5))
                rel_strength_5d = (stock_ret_5 - etf_ret_5).rename("market_sector_rel_strength_5d")
                
                features = features.join(rel_strength_1d.reindex(df.index).ffill())
                features = features.join(rel_strength_5d.reindex(df.index).ffill())
            else:
                features["market_sector_rel_strength_1d"] = 0.0
                features["market_sector_rel_strength_5d"] = 0.0
        except Exception as e:
            features["market_spy_return_1d"] = 0.0
            features["market_spy_rsi"] = 50.0
            features["market_vix_level"] = 15.0
            features["market_vix_roc_1d"] = 0.0
            features["market_sector_rel_strength_1d"] = 0.0
            features["market_sector_rel_strength_5d"] = 0.0

    # 2b. Longer-memory features
    if config.enable_long_memory:
        features["rsi_60"] = compute_rsi(close, period=60)
        features["rsi_120"] = compute_rsi(close, period=120)
        features["momentum_60"] = close / close.shift(60) - 1
        features["momentum_120"] = close / close.shift(120) - 1
        log_returns = np.log(close / close.shift(1))
        features["vol_60d"] = log_returns.rolling(60).std() * np.sqrt(252)
        features["vol_120d"] = log_returns.rolling(120).std() * np.sqrt(252)
        roll_high_252 = high.rolling(252, min_periods=20).max()
        roll_low_252 = low.rolling(252, min_periods=20).min()
        features["dist_52w_high"] = (roll_high_252 - close) / roll_high_252
        features["dist_52w_low"] = (close - roll_low_252) / roll_low_252

    # 2c. Volume-price interaction features
    if config.enable_vol_price and "Volume" in df and not df["Volume"].isna().all():
        price_roc_5 = close.pct_change(5)
        volume_sma_20 = volume.rolling(20).mean()
        vol_sma_roc_5 = volume_sma_20.pct_change(5)
        features["divergence_price_vol_5d"] = np.sign(price_roc_5) * np.sign(vol_sma_roc_5)
        adl_denom = (high - low).replace(0, 1e-8)
        adl_mult = ((close - low) - (high - close)) / adl_denom
        adl = (adl_mult * volume).cumsum()
        features["acc_dist_zscore"] = compute_zscore(adl)

    # 2d. Calendar features
    if config.enable_calendar:
        day_of_week = df.index.dayofweek
        features["cyclical_dow_sin"] = np.sin(2 * np.pi * day_of_week / 7)
        features["cyclical_dow_cos"] = np.cos(2 * np.pi * day_of_week / 7)
        day_of_month = df.index.day
        features["cyclical_dom_sin"] = np.sin(2 * np.pi * (day_of_month - 1) / 31)
        features["cyclical_dom_cos"] = np.cos(2 * np.pi * (day_of_month - 1) / 31)
        features["earnings_countdown"] = np.nan
        if symbol:
            try:
                import yfinance as yf
                ticker = yf.Ticker(symbol)
                cal = ticker.calendar
                if cal is not None and "Earnings Date" in cal:
                    earnings_dates = cal["Earnings Date"]
                    if len(earnings_dates) > 0:
                        next_earnings = pd.to_datetime(earnings_dates[0]).tz_localize(None)
                        idx_dates = df.index.tz_localize(None)
                        days_until = (next_earnings - idx_dates).days
                        features["earnings_countdown"] = np.where(days_until >= 0, days_until, np.nan)
            except Exception:
                pass

    # Fit GARCH and HMM features prior to dropping NaNs
    from ml.models.volatility.garch_model import GARCHVolatilityModel
    from ml.models.regime.hmm_regime_detector import HMMRegimeDetector
    
    daily_log_returns = pd.Series(np.log(close / close.shift(1)), name="log_return")
    garch_vol_1d = pd.Series(np.nan, index=df.index)
    garch_persistence = pd.Series(np.nan, index=df.index)
    try:
        garch_model = GARCHVolatilityModel()
        valid_returns = daily_log_returns.dropna()
        if len(valid_returns) >= 10:
            fit_len = min(len(valid_returns), 150)
            garch_model.fit(valid_returns.iloc[:fit_len])
            omega = garch_model.params.omega
            alpha = garch_model.params.alpha
            beta = garch_model.params.beta
            persistence = garch_model.params.persistence
            
            r = valid_returns.values
            n = len(r)
            sigma2 = np.empty(n)
            sigma2[0] = np.var(r[:fit_len])
            for i in range(1, n):
                sigma2[i] = omega + alpha * r[i-1]**2 + beta * sigma2[i-1]
            vol_forecast = np.sqrt(sigma2 * 252)
            garch_vol_1d.loc[valid_returns.index] = vol_forecast
            garch_persistence.loc[valid_returns.index] = persistence
    except Exception:
        pass
    features["garch_vol_1d"] = garch_vol_1d
    features["garch_vol"] = garch_vol_1d  # keep for test compatibility
    features["garch_persistence"] = garch_persistence

    try:
        hmm_detector = HMMRegimeDetector(n_regimes=3)
        hmm_detector.fit(daily_log_returns)
        features = hmm_detector.add_regime_features(features, daily_log_returns)
    except Exception:
        pass

    if drop_na:
        features = features.dropna()
    return features
