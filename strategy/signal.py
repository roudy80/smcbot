"""
Signal generation: combines M5 trend context (MSS) with M1 FVG entry.

Logic:
  1. On M5: detect a recent MSS (bullish or bearish)
  2. On M1: find an unfilled FVG in the SAME direction as the M5 MSS
  3. The FVG zone becomes the entry zone. Entry triggers when price re-enters
     the FVG (touches the top of a bull FVG or bot of a bear FVG).
  4. Emit a Signal with entry, stop_loss, take_profit, and direction.
"""

from dataclasses import dataclass
from datetime import datetime
import pandas as pd

from strategy.fvg import find_unfilled_fvgs
from strategy.mss import get_recent_mss
import config


@dataclass
class Signal:
    symbol:      str
    direction:   str        # "long" or "short"
    entry:       float      # price to enter at (FVG midpoint for limit orders)
    stop_loss:   float
    take_profit: float
    fvg_top:     float
    fvg_bot:     float
    mss_level:   float
    timestamp:   datetime
    timeframe:   str        # "M1" — always M1 FVG entry


def generate_signal(
    symbol: str,
    m5_df: pd.DataFrame,
    m1_df: pd.DataFrame,
    mss_lookback:  int = 50,
    fvg_lookback:  int = 30,
    swing_length:  int = 5,
    min_gap_pct:   float = 0.05,
) -> Signal | None:
    """
    Run the full signal generation pipeline for one symbol.

    Args:
        symbol:       Ticker symbol
        m5_df:        Closed M5 OHLCV candles (DatetimeIndex)
        m1_df:        Closed M1 OHLCV candles (DatetimeIndex)
        mss_lookback: How many M5 candles back to look for MSS
        fvg_lookback: How many M1 candles back to look for unfilled FVGs

    Returns:
        Signal if all conditions align, else None.
    """
    # Step 1: Get M5 structural context
    mss = get_recent_mss(m5_df, lookback=mss_lookback, swing_length=swing_length)
    if mss is None:
        return None

    # Step 2: Find M1 FVGs aligned with the M5 MSS direction
    fvgs = find_unfilled_fvgs(m1_df, lookback=fvg_lookback)
    aligned = [f for f in fvgs if f["direction"] == mss["direction"]]
    if not aligned:
        return None

    # Use the most recent aligned FVG
    fvg = aligned[-1]

    # Step 3: Check if current M1 price is at or inside the FVG zone
    # (price has returned to the gap — this is the entry trigger)
    last_m1 = m1_df.iloc[-1]
    current_price = last_m1["close"]

    in_bull_zone = (fvg["direction"] == "bull"
                    and current_price <= fvg["top"]
                    and current_price >= fvg["bot"])
    in_bear_zone = (fvg["direction"] == "bear"
                    and current_price >= fvg["bot"]
                    and current_price <= fvg["top"])

    if not (in_bull_zone or in_bear_zone):
        return None

    # Step 4: Calculate entry, SL, TP
    direction = "long" if fvg["direction"] == "bull" else "short"
    entry     = fvg["midpoint"]
    sl_dist   = entry * (config.STOP_LOSS_PCT / 100)

    if direction == "long":
        stop_loss   = entry - sl_dist
        take_profit = entry + sl_dist * config.RR_RATIO
    else:
        stop_loss   = entry + sl_dist
        take_profit = entry - sl_dist * config.RR_RATIO

    return Signal(
        symbol      = symbol,
        direction   = direction,
        entry       = round(entry, 4),
        stop_loss   = round(stop_loss, 4),
        take_profit = round(take_profit, 4),
        fvg_top     = fvg["top"],
        fvg_bot     = fvg["bot"],
        mss_level   = mss["level"],
        timestamp   = m1_df.index[-1].to_pydatetime(),
        timeframe   = "M1",
    )
