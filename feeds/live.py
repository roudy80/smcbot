"""
Live WebSocket feed using alpaca-py.
Aggregates real-time bar updates and maintains a rolling OHLCV buffer
for both M1 and M5 timeframes per symbol.

The `on_bar_closed` callback is invoked with (symbol, timeframe, df)
each time a new closed bar is available — this is the hook that triggers
signal generation in bot.py.
"""

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from typing import Callable

import pandas as pd
from alpaca.data.live import StockDataStream

import config


class LiveFeed:
    def __init__(self, on_bar_closed: Callable):
        """
        Args:
            on_bar_closed: Callable(symbol: str, timeframe: str, df: pd.DataFrame)
                           Called whenever a new M1 or M5 bar closes.
        """
        self._on_bar_closed = on_bar_closed
        self._stream        = StockDataStream(
            api_key    = config.ALPACA_API_KEY,
            secret_key = config.ALPACA_SECRET_KEY,
        )

        # Rolling buffers: {symbol: {"1Min": df, "5Min": df}}
        self._buffers: dict[str, dict[str, pd.DataFrame]] = defaultdict(
            lambda: {"1Min": pd.DataFrame(), "5Min": pd.DataFrame()}
        )

        # M5 aggregation state: {symbol: list_of_m1_bars_in_current_5min_window}
        self._m5_pending: dict[str, list] = defaultdict(list)

        self._stream.subscribe_bars(self._handle_bar, *config.SYMBOLS)

    async def _handle_bar(self, bar):
        """
        Alpaca streams M1 bars. We:
        1. Append to M1 buffer → fire on_bar_closed("1Min")
        2. Accumulate into M5 buffer → fire on_bar_closed("5Min") every 5 bars
        """
        symbol = bar.symbol
        ts     = pd.Timestamp(bar.timestamp, tz="UTC")

        new_row = pd.DataFrame([{
            "open":   bar.open,
            "high":   bar.high,
            "low":    bar.low,
            "close":  bar.close,
            "volume": bar.volume,
        }], index=[ts])

        # --- M1 buffer ---
        m1 = self._buffers[symbol]["1Min"]
        m1 = pd.concat([m1, new_row]).tail(200)  # keep last 200 M1 bars
        self._buffers[symbol]["1Min"] = m1
        self._on_bar_closed(symbol, "1Min", m1.copy())

        # --- M5 aggregation ---
        pending = self._m5_pending[symbol]
        pending.append(new_row)

        # A new M5 bar closes every time the minute is :00, :05, :10, etc.
        if ts.minute % 5 == 4:  # 4th minute of each 5-min window closes the bar
            m5_bar = pd.DataFrame([{
                "open":   pending[0]["open"].iloc[0],
                "high":   max(r["high"].iloc[0] for r in pending),
                "low":    min(r["low"].iloc[0]  for r in pending),
                "close":  pending[-1]["close"].iloc[0],
                "volume": sum(r["volume"].iloc[0] for r in pending),
            }], index=[pending[-1].index[0]])

            m5 = self._buffers[symbol]["5Min"]
            m5 = pd.concat([m5, m5_bar]).tail(100)  # keep last 100 M5 bars
            self._buffers[symbol]["5Min"] = m5
            self._m5_pending[symbol] = []
            self._on_bar_closed(symbol, "5Min", m5.copy())

    def run(self):
        """Start the blocking event loop."""
        print(f"[feed] Starting live stream for: {config.SYMBOLS}")
        self._stream.run()

    def stop(self):
        self._stream.stop()
