"""
Live feed using polling instead of WebSocket.
Fetches latest bars via yfinance every 60 seconds.
Avoids Alpaca's free-tier WebSocket connection limit entirely.

The on_bar_closed callback fires whenever a new M1 or M5 bar
is detected since the last poll.
"""

import time
import threading
from datetime import datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

import config

ET = ZoneInfo("America/New_York")
POLL_INTERVAL = 60  # seconds between polls


class LiveFeed:
    def __init__(self, on_bar_closed: Callable):
        self._callback  = on_bar_closed
        self._running   = False
        self._thread    = None

        # Track the last bar timestamp seen per symbol+timeframe
        self._last_seen: dict[str, pd.Timestamp] = {}

        # Rolling buffers
        self._buffers: dict[str, dict[str, pd.DataFrame]] = {
            s: {"1Min": pd.DataFrame(), "5Min": pd.DataFrame()}
            for s in config.SYMBOLS
        }

    def _fetch_latest(self, symbol: str, interval: str, period: str) -> pd.DataFrame:
        try:
            df = yf.download(symbol, period=period, interval=interval,
                             auto_adjust=True, progress=False, threads=False)
            if df.empty:
                return pd.DataFrame()
            df.columns = [c.lower() if isinstance(c, str) else c[0].lower()
                          for c in df.columns]
            df = df[["open", "high", "low", "close", "volume"]]
            df.index = pd.to_datetime(df.index, utc=True)
            # Drop the last (potentially incomplete) bar
            return df.iloc[:-1]
        except Exception as e:
            print(f"[feed] fetch error {symbol} {interval}: {e}")
            return pd.DataFrame()

    def _poll(self):
        print(f"[feed] Polling {'  '.join(config.SYMBOLS)} every {POLL_INTERVAL}s")
        while self._running:
            now_et = datetime.now(ET)

            for symbol in config.SYMBOLS:
                # --- M1 ---
                m1 = self._fetch_latest(symbol, "1m", "1d")
                if not m1.empty:
                    key = f"{symbol}_1Min"
                    last = self._last_seen.get(key)
                    new_bars = m1[m1.index > last] if last is not None else m1.iloc[-5:]
                    if not new_bars.empty:
                        buf = pd.concat([self._buffers[symbol]["1Min"], new_bars]).tail(200)
                        self._buffers[symbol]["1Min"] = buf
                        self._last_seen[key] = m1.index[-1]
                        self._callback(symbol, "1Min", buf.copy())

                # --- M5 ---
                m5 = self._fetch_latest(symbol, "5m", "5d")
                if not m5.empty:
                    key = f"{symbol}_5Min"
                    last = self._last_seen.get(key)
                    new_bars = m5[m5.index > last] if last is not None else m5.iloc[-5:]
                    if not new_bars.empty:
                        buf = pd.concat([self._buffers[symbol]["5Min"], new_bars]).tail(100)
                        self._buffers[symbol]["5Min"] = buf
                        self._last_seen[key] = m5.index[-1]
                        self._callback(symbol, "5Min", buf.copy())

            # Sleep in 5s increments so stop() is responsive
            for _ in range(POLL_INTERVAL // 5):
                if not self._running:
                    break
                time.sleep(5)

    def run(self):
        """Start polling loop (blocking)."""
        self._running = True
        self._poll()

    def stop(self):
        self._running = False
