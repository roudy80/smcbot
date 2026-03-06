"""
Market Structure Shift (MSS) detection.

Definitions used here (ICT-aligned):
  - Swing High: a candle whose high is higher than the N candles on each side.
  - Swing Low:  a candle whose low is lower than the N candles on each side.
  - BOS (Break of Structure): price closes ABOVE a prior swing high (bullish BOS)
    or BELOW a prior swing low (bearish BOS).
  - MSS: first BOS in the opposite direction of the prevailing trend, signaling
    a potential trend reversal. We treat this as the setup prerequisite before
    an FVG entry.
"""

import pandas as pd
import numpy as np


def find_swing_points(df: pd.DataFrame, swing_length: int = 5) -> pd.DataFrame:
    """
    Add swing_high and swing_low boolean columns to df.
    A swing high/low requires `swing_length` candles on each side.
    """
    df = df.copy()
    highs = df["high"].values
    lows  = df["low"].values
    n     = len(df)

    df["swing_high"] = False
    df["swing_low"]  = False

    for i in range(swing_length, n - swing_length):
        left_h  = highs[i - swing_length:i]
        right_h = highs[i + 1:i + swing_length + 1]
        if highs[i] > max(left_h) and highs[i] > max(right_h):
            df.iloc[i, df.columns.get_loc("swing_high")] = True

        left_l  = lows[i - swing_length:i]
        right_l = lows[i + 1:i + swing_length + 1]
        if lows[i] < min(left_l) and lows[i] < min(right_l):
            df.iloc[i, df.columns.get_loc("swing_low")] = True

    return df


def detect_mss(df: pd.DataFrame, swing_length: int = 5) -> pd.DataFrame:
    """
    Detect Market Structure Shifts.

    Returns df with added columns:
        mss_bull (bool) - bullish MSS: bearish swing low broken to upside
        mss_bear (bool) - bearish MSS: bullish swing high broken to downside
        mss_level (float) - the swing level that was broken
    """
    df = find_swing_points(df, swing_length)
    n  = len(df)
    closes = df["close"].values
    highs  = df["high"].values
    lows   = df["low"].values

    df["mss_bull"]  = False
    df["mss_bear"]  = False
    df["mss_level"] = float("nan")

    # Track most recent swing points
    last_swing_high_price = None
    last_swing_high_idx   = None
    last_swing_low_price  = None
    last_swing_low_idx    = None

    for i in range(swing_length, n):
        # Check MSS BEFORE updating swing state — a bar can both be a new
        # swing point AND break the previous one; we want to catch the break.

        # Bullish MSS: current close breaks above last swing high
        if (last_swing_high_price is not None
                and last_swing_high_idx is not None
                and i > last_swing_high_idx
                and closes[i] > last_swing_high_price):
            df.iloc[i, df.columns.get_loc("mss_bull")]  = True
            df.iloc[i, df.columns.get_loc("mss_level")] = last_swing_high_price
            last_swing_high_price = None  # consumed, reset

        # Bearish MSS: current close breaks below last swing low
        elif (last_swing_low_price is not None
                and last_swing_low_idx is not None
                and i > last_swing_low_idx
                and closes[i] < last_swing_low_price):
            df.iloc[i, df.columns.get_loc("mss_bear")]  = True
            df.iloc[i, df.columns.get_loc("mss_level")] = last_swing_low_price
            last_swing_low_price = None  # consumed, reset

        # Update swing state AFTER MSS check
        if df.iloc[i]["swing_high"]:
            last_swing_high_price = highs[i]
            last_swing_high_idx   = i

        if df.iloc[i]["swing_low"]:
            last_swing_low_price = lows[i]
            last_swing_low_idx   = i

    return df


def get_recent_mss(df: pd.DataFrame, lookback: int = 50, swing_length: int = 5) -> dict | None:
    """
    Return the most recent MSS within `lookback` candles, or None.
    Used by signal.py to confirm structural context before FVG entry.
    """
    window = df.iloc[-lookback:].copy()
    mss_df = detect_mss(window, swing_length)

    # Find the most recent MSS (scan from newest to oldest)
    for i in range(len(mss_df) - 1, -1, -1):
        row = mss_df.iloc[i]
        if row["mss_bull"] or row["mss_bear"]:
            return {
                "timestamp": mss_df.index[i],
                "direction": "bull" if row["mss_bull"] else "bear",
                "level":     row["mss_level"],
            }
    return None
