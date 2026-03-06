"""
Fetch and cache historical OHLCV data.

Uses yfinance (free, no API key, years of data) for backtesting.
Alpaca is kept for live order execution only.
Caches to data/<symbol>_<timeframe>.parquet to avoid re-fetching.
"""

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

# yfinance interval strings
_YF_INTERVAL = {
    "1Min":  "1m",
    "5Min":  "5m",
    "15Min": "15m",
    "1H":    "1h",
    "1D":    "1d",
}

# yfinance only allows 7 days of 1m data, 60 days of 5m/15m
_MAX_DAYS = {
    "1Min":  7,
    "5Min":  59,
    "15Min": 59,
    "1H":    730,
    "1D":    3650,
}


def fetch(
    symbol:    str,
    timeframe: str,
    days:      int = 30,
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    Fetch OHLCV bars for `symbol` going back `days` calendar days.
    Cached as parquet. Set use_cache=False to force re-fetch.

    Returns DataFrame with DatetimeIndex (UTC), columns: open, high, low, close, volume.
    """
    if timeframe not in _YF_INTERVAL:
        raise ValueError(f"Unknown timeframe: {timeframe}. Use: {list(_YF_INTERVAL)}")

    # Clamp days to what yfinance allows for this timeframe
    max_days = _MAX_DAYS[timeframe]
    if days > max_days:
        print(f"[fetch] {symbol} {timeframe}: clamping {days}d → {max_days}d (yfinance limit)")
        days = max_days

    cache_path = DATA_DIR / f"{symbol}_{timeframe}_{days}d.parquet"

    if use_cache and cache_path.exists():
        age_hours = (datetime.now().timestamp() - cache_path.stat().st_mtime) / 3600
        if age_hours < 1:
            df = pd.read_parquet(cache_path)
            print(f"[cache] {symbol} {timeframe} — {len(df)} bars")
            return df

    end   = datetime.utcnow()
    start = end - timedelta(days=days)

    ticker = yf.Ticker(symbol)
    df = ticker.history(
        start    = start.strftime("%Y-%m-%d"),
        end      = end.strftime("%Y-%m-%d"),
        interval = _YF_INTERVAL[timeframe],
        auto_adjust = True,
    )

    if df.empty:
        raise ValueError(f"No data returned for {symbol} {timeframe}")

    df.index = pd.to_datetime(df.index, utc=True)
    df.columns = [c.lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]].sort_index()

    # Drop pre/post market rows (only keep 09:30–16:00 ET)
    df = df.between_time("13:30", "20:00")  # UTC equivalent of 09:30–16:00 ET

    df.to_parquet(cache_path)
    print(f"[fetch] {symbol} {timeframe} — {len(df)} bars fetched")
    return df


def fetch_multi(
    symbols:   list[str],
    timeframe: str,
    days:      int = 30,
) -> dict[str, pd.DataFrame]:
    """Fetch historical data for multiple symbols. Returns {symbol: df}."""
    return {s: fetch(s, timeframe, days) for s in symbols}
