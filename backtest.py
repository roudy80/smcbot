"""
Walk-forward backtester for the SMC FVG+MSS strategy.

Usage:
    python backtest.py                    # default: SPY, QQQ, 90 days
    python backtest.py --symbols SPY AAPL --days 60
    python backtest.py --no-cache         # force fresh data fetch

Output:
    - Prints metrics table to console
    - Saves results/backtest_YYYY-MM-DD.json
    - Saves results/backtest_YYYY-MM-DD_equity.csv
"""

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

import config
from feeds.historical import fetch
from strategy.fvg import find_unfilled_fvgs
from strategy.mss import get_recent_mss
from strategy.signal import generate_signal, Signal

RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)

# ---- Backtest parameters (override via CLI) ----
DEFAULT_SYMBOLS = config.SYMBOLS
DEFAULT_DAYS    = 90

# Walk-forward: train on first 70%, test on last 30%
TRAIN_SPLIT = 0.70


def simulate_trades(
    symbol:    str,
    m5_df:    pd.DataFrame,
    m1_df:    pd.DataFrame,
    sl_pct:   float = config.STOP_LOSS_PCT,
    rr_ratio: float = config.RR_RATIO,
    cooldown_bars: int = 15,
) -> list[dict]:
    """
    Walk through M1 candles sequentially (no lookahead).
    For each closed M1 bar, run the signal logic against available M5 context.
    Simulate bracket order execution with 0.05% slippage.

    Returns list of trade records.
    """
    trades = []
    SLIPPAGE = 0.0005  # 0.05% realistic slippage

    last_signal_bar = -cooldown_bars  # allow first signal immediately

    # Minimum bars needed before we can compute MSS on M5
    if len(m5_df) < 20 or len(m1_df) < 15:
        print(f"  [backtest] {symbol}: not enough bars")
        return trades

    # Build a mapping from M1 timestamp → M5 slice index so we can
    # pass only past M5 bars to generate_signal at each step (no lookahead).
    m5_times = m5_df.index
    m1_times = m1_df.index

    for i in range(15, len(m1_df) - 1):
        if i - last_signal_bar < cooldown_bars:
            continue

        current_m1_time = m1_times[i]
        # Only use M5 bars whose timestamp <= current M1 bar
        m5_window = m5_df[m5_df.index <= current_m1_time]
        if len(m5_window) < 20:
            continue

        m1_window = m1_df.iloc[:i + 1]
        sig = generate_signal(symbol=symbol, m5_df=m5_window, m1_df=m1_window)
        if sig is None:
            continue

        last_signal_bar = i

        # Simulated fill: next bar open + slippage
        next_bar  = m1_df.iloc[i + 1]
        if sig.direction == "long":
            fill_price = next_bar["open"] * (1 + SLIPPAGE)
            sl_price   = fill_price * (1 - sl_pct / 100)
            tp_price   = fill_price * (1 + sl_pct * rr_ratio / 100)
        else:
            fill_price = next_bar["open"] * (1 - SLIPPAGE)
            sl_price   = fill_price * (1 + sl_pct / 100)
            tp_price   = fill_price * (1 - sl_pct * rr_ratio / 100)

        # Walk forward bars to find exit
        outcome   = "timeout"
        exit_price = m1_df.iloc[-1]["close"]  # default: exit at end of data

        for j in range(i + 2, min(i + 200, len(m1_df))):
            future = m1_df.iloc[j]
            if sig.direction == "long":
                if future["low"] <= sl_price:
                    exit_price = sl_price
                    outcome    = "stop_loss"
                    break
                if future["high"] >= tp_price:
                    exit_price = tp_price
                    outcome    = "take_profit"
                    break
            else:
                if future["high"] >= sl_price:
                    exit_price = sl_price
                    outcome    = "stop_loss"
                    break
                if future["low"] <= tp_price:
                    exit_price = tp_price
                    outcome    = "take_profit"
                    break

        pnl_pct = (exit_price - fill_price) / fill_price * 100
        if sig.direction == "short":
            pnl_pct = -pnl_pct

        trades.append({
            "symbol":     symbol,
            "timestamp":  str(m1_df.index[i]),
            "direction":  sig.direction,
            "fill_price": round(fill_price, 4),
            "sl_price":   round(sl_price, 4),
            "tp_price":   round(tp_price, 4),
            "exit_price": round(exit_price, 4),
            "outcome":    outcome,
            "pnl_pct":    round(pnl_pct, 4),
        })

    return trades


def compute_metrics(trades: list[dict], label: str = "") -> dict:
    if not trades:
        return {"label": label, "total_trades": 0}

    wins   = [t for t in trades if t["outcome"] == "take_profit"]
    losses = [t for t in trades if t["outcome"] == "stop_loss"]
    pnls   = [t["pnl_pct"] for t in trades]

    win_rate      = len(wins) / len(trades) * 100
    avg_win       = sum(t["pnl_pct"] for t in wins)  / len(wins)  if wins   else 0
    avg_loss      = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0
    gross_profit  = sum(t["pnl_pct"] for t in wins)
    gross_loss    = abs(sum(t["pnl_pct"] for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss else float("inf")

    # Max drawdown on pnl_pct series
    equity = 0
    peak   = 0
    max_dd = 0
    for p in pnls:
        equity += p
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    return {
        "label":         label,
        "total_trades":  len(trades),
        "wins":          len(wins),
        "losses":        len(losses),
        "win_rate":      round(win_rate, 1),
        "avg_win_pct":   round(avg_win, 3),
        "avg_loss_pct":  round(avg_loss, 3),
        "profit_factor": round(profit_factor, 2),
        "total_pnl_pct": round(sum(pnls), 3),
        "max_drawdown":  round(max_dd, 3),
        "signals_per_day": round(len(trades) / (len(pnls) / 390) if pnls else 0, 2),
    }


def run_backtest(symbols: list[str], days: int, use_cache: bool = True):
    all_trades      = []
    train_trades    = []
    test_trades     = []

    for symbol in symbols:
        print(f"\n[backtest] Fetching {symbol}...")
        m5 = fetch(symbol, config.M5_TIMEFRAME, days=days, use_cache=use_cache)
        m1 = fetch(symbol, config.M1_TIMEFRAME, days=days, use_cache=use_cache)

        # Walk-forward split
        split_idx = int(len(m1) * TRAIN_SPLIT)
        m1_train  = m1.iloc[:split_idx]
        m1_test   = m1.iloc[split_idx:]
        m5_split  = int(len(m5) * TRAIN_SPLIT)
        m5_train  = m5.iloc[:m5_split]
        m5_test   = m5.iloc[m5_split:]

        print(f"  Train: {len(m1_train)} M1 bars | Test: {len(m1_test)} M1 bars")

        train = simulate_trades(symbol, m5_train, m1_train)
        test  = simulate_trades(symbol, m5_test,  m1_test)

        train_trades.extend(train)
        test_trades.extend(test)
        all_trades.extend(train + test)

        print(f"  Train: {len(train)} trades | Test: {len(test)} trades")

    print("\n" + "=" * 60)

    train_metrics = compute_metrics(train_trades, "TRAIN (in-sample)")
    test_metrics  = compute_metrics(test_trades,  "TEST  (out-of-sample)")
    total_metrics = compute_metrics(all_trades,   "TOTAL")

    for m in [train_metrics, test_metrics, total_metrics]:
        print(f"\n{m['label']}")
        print(f"  Trades: {m.get('total_trades', 0)} | Win Rate: {m.get('win_rate', 0)}%")
        print(f"  Avg Win: {m.get('avg_win_pct', 0)}% | Avg Loss: {m.get('avg_loss_pct', 0)}%")
        print(f"  Profit Factor: {m.get('profit_factor', 0)} | Total P&L: {m.get('total_pnl_pct', 0)}%")
        print(f"  Max Drawdown: {m.get('max_drawdown', 0)}%")

    # Overfit warning
    if train_metrics.get("win_rate", 0) - test_metrics.get("win_rate", 0) > 15:
        print("\n  WARNING: Train/test win rate gap > 15% — possible overfitting")

    # Save results
    today = date.today()
    output = {
        "date":     str(today),
        "symbols":  symbols,
        "days":     days,
        "train":    train_metrics,
        "test":     test_metrics,
        "total":    total_metrics,
        "trades":   all_trades,
    }

    result_path = RESULTS_DIR / f"backtest_{today}.json"
    result_path.write_text(json.dumps(output, indent=2))
    print(f"\n[backtest] Results saved to {result_path}")

    equity_path = RESULTS_DIR / f"backtest_{today}_equity.csv"
    pd.DataFrame(all_trades).to_csv(equity_path, index=False)
    print(f"[backtest] Equity curve saved to {equity_path}")

    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--days",    type=int,   default=DEFAULT_DAYS)
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    run_backtest(
        symbols   = args.symbols,
        days      = args.days,
        use_cache = not args.no_cache,
    )
