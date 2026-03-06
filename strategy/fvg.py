"""
Fair Value Gap (FVG) detection on closed OHLCV candles.

A bullish FVG exists when:
    candle[i-1].high < candle[i+1].low   (gap between prev high and next low)

A bearish FVG exists when:
    candle[i-1].low > candle[i+1].high   (gap between prev low and next high)

Candle i is the "gap candle". We only evaluate fully closed candles — never
the current live candle.
"""

import pandas as pd


def detect_fvg(df: pd.DataFrame, min_gap_pct: float = 0.05) -> pd.DataFrame:
    """
    Detect Fair Value Gaps in a closed-candle OHLCV DataFrame.

    Args:
        df: DataFrame with columns [open, high, low, close, volume].
            Index must be a DatetimeIndex. All candles assumed closed.
        min_gap_pct: Minimum gap size as % of candle[i] close price.
                     Filters out noise / micro-gaps.

    Returns:
        Original df with added columns:
            fvg_bull  (bool)  - bullish FVG detected at this candle
            fvg_bear  (bool)  - bearish FVG detected at this candle
            fvg_top   (float) - upper boundary of the gap
            fvg_bot   (float) - lower boundary of the gap
    """
    df = df.copy()
    df["fvg_bull"] = False
    df["fvg_bear"] = False
    df["fvg_top"]  = float("nan")
    df["fvg_bot"]  = float("nan")

    highs  = df["high"].values
    lows   = df["low"].values
    closes = df["close"].values
    n      = len(df)

    for i in range(1, n - 1):
        gap_top = None
        gap_bot = None

        # Bullish FVG: prev high < next low
        if highs[i - 1] < lows[i + 1]:
            gap_bot = highs[i - 1]
            gap_top = lows[i + 1]

        # Bearish FVG: prev low > next high
        elif lows[i - 1] > highs[i + 1]:
            gap_top = lows[i - 1]
            gap_bot = highs[i + 1]

        if gap_top is not None:
            gap_size_pct = (gap_top - gap_bot) / closes[i] * 100
            if gap_size_pct >= min_gap_pct:
                is_bull = highs[i - 1] < lows[i + 1]
                df.iloc[i, df.columns.get_loc("fvg_bull")] = is_bull
                df.iloc[i, df.columns.get_loc("fvg_bear")] = not is_bull
                df.iloc[i, df.columns.get_loc("fvg_top")]  = gap_top
                df.iloc[i, df.columns.get_loc("fvg_bot")]  = gap_bot

    return df


def find_unfilled_fvgs(df: pd.DataFrame, lookback: int = 50) -> list[dict]:
    """
    Return list of FVGs from the last `lookback` candles that have NOT been
    filled (price has not re-entered the gap zone).

    An FVG is "filled" when a subsequent candle's range overlaps the gap.
    """
    fvg_df = detect_fvg(df)
    unfilled = []

    # Only look at the lookback window
    window = fvg_df.iloc[-lookback:]

    for idx in range(len(window) - 1):
        row = window.iloc[idx]
        if not (row["fvg_bull"] or row["fvg_bear"]):
            continue

        top = row["fvg_top"]
        bot = row["fvg_bot"]
        filled = False

        # Check all candles AFTER this FVG candle
        for future_idx in range(idx + 1, len(window)):
            future = window.iloc[future_idx]
            # Filled if future candle's range enters the gap
            if future["low"] <= top and future["high"] >= bot:
                filled = True
                break

        if not filled:
            unfilled.append({
                "timestamp": window.index[idx],
                "direction": "bull" if row["fvg_bull"] else "bear",
                "top":       top,
                "bot":       bot,
                "midpoint":  (top + bot) / 2,
            })

    return unfilled
