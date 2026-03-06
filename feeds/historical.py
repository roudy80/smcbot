"""
Fetch and cache historical OHLCV data via alpaca-py.
Caches to data/<symbol>_<timeframe>.parquet to avoid re-fetching.
"""

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

import config

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

_data_client: StockHistoricalDataClient | None = None


def get_data_client() -> StockHistoricalDataClient:
    global _data_client
    if _data_client is None:
        _data_client = StockHistoricalDataClient(
            api_key    = config.ALPACA_API_KEY,
            secret_key = config.ALPACA_SECRET_KEY,
        )
    return _data_client


def _timeframe_obj(tf: str) -> TimeFrame:
    mapping = {
        "1Min":  TimeFrame(1,  TimeFrameUnit.Minute),
        "5Min":  TimeFrame(5,  TimeFrameUnit.Minute),
        "15Min": TimeFrame(15, TimeFrameUnit.Minute),
        "1H":    TimeFrame(1,  TimeFrameUnit.Hour),
        "1D":    TimeFrame(1,  TimeFrameUnit.Day),
    }
    if tf not in mapping:
        raise ValueError(f"Unknown timeframe: {tf}. Use one of {list(mapping)}")
    return mapping[tf]


def fetch(
    symbol:    str,
    timeframe: str,
    days:      int = 30,
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    Fetch OHLCV bars for `symbol` going back `days` calendar days.
    Results are cached as parquet. Set use_cache=False to force re-fetch.

    Returns DataFrame with DatetimeIndex (UTC), columns: open, high, low, close, volume.
    """
    cache_path = DATA_DIR / f"{symbol}_{timeframe}_{days}d.parquet"

    if use_cache and cache_path.exists():
        # Refresh if cache is older than 1 hour
        age_hours = (datetime.now().timestamp() - cache_path.stat().st_mtime) / 3600
        if age_hours < 1:
            df = pd.read_parquet(cache_path)
            print(f"[cache] {symbol} {timeframe} ({len(df)} bars from cache)")
            return df

    end   = datetime.utcnow()
    start = end - timedelta(days=days)

    req = StockBarsRequest(
        symbol_or_symbols = symbol,
        timeframe         = _timeframe_obj(timeframe),
        start             = start,
        end               = end,
    )

    bars = get_data_client().get_stock_bars(req)
    df   = bars.df

    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level="symbol")

    df.index = pd.to_datetime(df.index, utc=True)
    df = df[["open", "high", "low", "close", "volume"]].sort_index()

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
