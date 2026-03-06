"""
Crypto data feed — uses Alpaca's FREE crypto data (no subscription needed).
Polls every 60s, works 24/7 unlike stocks.
"""

import time
import threading
from datetime import datetime, timedelta
from typing import Callable

import pandas as pd
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

import config

POLL_INTERVAL = 60

_client = None
def get_client():
    global _client
    if _client is None:
        _client = CryptoHistoricalDataClient()  # no API key needed
    return _client


def fetch_crypto(symbol: str, timeframe: str, days: int = 3) -> pd.DataFrame:
    """Fetch crypto OHLCV. Symbol format: 'BTC/USD'"""
    tf_map = {
        "1Min":  TimeFrame(1,  TimeFrameUnit.Minute),
        "5Min":  TimeFrame(5,  TimeFrameUnit.Minute),
        "15Min": TimeFrame(15, TimeFrameUnit.Minute),
    }
    req = CryptoBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=tf_map[timeframe],
        start=datetime.utcnow() - timedelta(days=days),
        end=datetime.utcnow(),
    )
    bars = get_client().get_crypto_bars(req)
    df = bars.df
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level="symbol")
    df.index = pd.to_datetime(df.index, utc=True)
    return df[["open","high","low","close","volume"]].sort_index()


class CryptoFeed:
    def __init__(self, symbols: list[str], on_bar_closed: Callable):
        self._symbols  = symbols
        self._callback = on_bar_closed
        self._running  = False
        self._last_seen: dict[str, pd.Timestamp] = {}
        self._buffers: dict[str, dict] = {
            s: {"1Min": pd.DataFrame(), "5Min": pd.DataFrame()}
            for s in symbols
        }

    def _poll(self):
        print(f"[crypto] Polling {self._symbols} every {POLL_INTERVAL}s (24/7)")
        while self._running:
            for symbol in self._symbols:
                for tf, days in [("1Min", 1), ("5Min", 3)]:
                    try:
                        df = fetch_crypto(symbol, tf, days=days)
                        if df.empty:
                            continue
                        # Drop last (incomplete) bar
                        df = df.iloc[:-1]
                        key  = f"{symbol}_{tf}"
                        last = self._last_seen.get(key)
                        new  = df[df.index > last] if last is not None else df.iloc[-5:]
                        if not new.empty:
                            buf = pd.concat([self._buffers[symbol][tf], new]).tail(300)
                            self._buffers[symbol][tf] = buf
                            self._last_seen[key] = df.index[-1]
                            self._callback(symbol, tf, buf.copy())
                    except Exception as e:
                        print(f"[crypto] error {symbol} {tf}: {e}")

            for _ in range(POLL_INTERVAL // 5):
                if not self._running: break
                time.sleep(5)

    def run(self):
        self._running = True
        self._poll()

    def run_background(self):
        t = threading.Thread(target=self.run, daemon=True)
        t.start()
        return t

    def stop(self):
        self._running = False
