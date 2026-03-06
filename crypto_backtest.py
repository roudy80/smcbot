"""
Crypto walk-forward backtester — 1H trend + 15Min entry.

Usage:
    python crypto_backtest.py              # BTC+ETH, 30 days
    python crypto_backtest.py --days 90
    python crypto_backtest.py --symbols BTC/USD SOL/USD --days 60
"""

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

import config
from feeds.crypto import fetch_crypto
from strategy.signal import generate_signal

RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)

TRAIN_SPLIT   = 0.70
SLIPPAGE_PCT  = 0.001   # 0.1% crypto slippage
CRYPTO_SL_PCT = 1.5     # 1.5% stop
CRYPTO_RR     = 2.0     # 1:2 R:R
COOLDOWN_BARS = 4       # 4 x 15Min = 1 hour


def simulate_crypto(symbol: str, h1_df: pd.DataFrame, m15_df: pd.DataFrame,
                    partial_tp: bool = True) -> list[dict]:
    trades = []
    last_signal_bar = -COOLDOWN_BARS

    if len(h1_df) < 20 or len(m15_df) < 15:
        print(f"  [crypto_bt] {symbol}: not enough bars")
        return trades

    m15_times = m15_df.index

    for i in range(15, len(m15_df) - 1):
        if i - last_signal_bar < COOLDOWN_BARS:
            continue

        t       = m15_times[i]
        h1_win  = h1_df[h1_df.index <= t]
        m15_win = m15_df.iloc[:i + 1]

        if len(h1_win) < 20:
            continue

        sig = generate_signal(
            symbol       = symbol,
            m5_df        = h1_win,
            m1_df        = m15_win,
            mss_lookback = 50,
            fvg_lookback = 20,
            swing_length = 5,
            min_gap_pct  = 0.10,
        )
        if sig is None:
            continue

        last_signal_bar = i
        next_bar        = m15_df.iloc[i + 1]

        if sig.direction == "long":
            fill  = next_bar["open"] * (1 + SLIPPAGE_PCT)
            sl    = fill * (1 - CRYPTO_SL_PCT / 100)
            tp    = fill * (1 + CRYPTO_SL_PCT * CRYPTO_RR / 100)
            tp_half = fill + (tp - fill) * 0.5
        else:
            fill  = next_bar["open"] * (1 - SLIPPAGE_PCT)
            sl    = fill * (1 + CRYPTO_SL_PCT / 100)
            tp    = fill * (1 - CRYPTO_SL_PCT * CRYPTO_RR / 100)
            tp_half = fill - (fill - tp) * 0.5

        outcome    = "timeout"
        exit_price = m15_df.iloc[-1]["close"]
        partial_hit = False
        be_stop     = sl  # start with original sl, move to break-even after partial

        for j in range(i + 2, min(i + 500, len(m15_df))):
            f = m15_df.iloc[j]
            if sig.direction == "long":
                if partial_tp and not partial_hit and f["high"] >= tp_half:
                    partial_hit = True
                    be_stop     = fill  # move stop to break-even
                if f["low"] <= be_stop:
                    exit_price = be_stop
                    outcome    = "break_even" if partial_hit else "stop_loss"
                    break
                if f["high"] >= tp:
                    exit_price = tp
                    outcome    = "take_profit"
                    break
            else:
                if partial_tp and not partial_hit and f["low"] <= tp_half:
                    partial_hit = True
                    be_stop     = fill
                if f["high"] >= be_stop:
                    exit_price = be_stop
                    outcome    = "break_even" if partial_hit else "stop_loss"
                    break
                if f["low"] <= tp:
                    exit_price = tp
                    outcome    = "take_profit"
                    break

        # For partial TP: blended PnL (50% at half-tp + 50% at exit)
        if partial_hit and outcome != "take_profit":
            half_pnl = (tp_half - fill) / fill * 100
            rest_pnl = (exit_price - fill) / fill * 100
            if sig.direction == "short":
                half_pnl = -half_pnl
                rest_pnl = -rest_pnl
            pnl_pct = (half_pnl + rest_pnl) / 2
        else:
            pnl_pct = (exit_price - fill) / fill * 100
            if sig.direction == "short":
                pnl_pct = -pnl_pct

        trades.append({
            "symbol":    symbol,
            "timestamp": str(t),
            "direction": sig.direction,
            "fill":      round(fill, 4),
            "sl":        round(sl, 4),
            "tp":        round(tp, 4),
            "exit":      round(exit_price, 4),
            "outcome":   outcome,
            "pnl_pct":   round(pnl_pct, 4),
        })

    return trades


def compute_metrics(trades: list[dict], label: str = "") -> dict:
    if not trades:
        return {"label": label, "total_trades": 0}

    wins   = [t for t in trades if t["outcome"] == "take_profit"]
    be     = [t for t in trades if t["outcome"] == "break_even"]
    losses = [t for t in trades if t["outcome"] == "stop_loss"]
    pnls   = [t["pnl_pct"] for t in trades]

    win_rate     = len(wins) / len(trades) * 100
    avg_win      = sum(t["pnl_pct"] for t in wins)   / len(wins)   if wins   else 0
    avg_loss     = sum(t["pnl_pct"] for t in losses)  / len(losses) if losses else 0
    gross_profit = sum(t["pnl_pct"] for t in wins)
    gross_loss   = abs(sum(t["pnl_pct"] for t in losses))
    pf           = gross_profit / gross_loss if gross_loss else float("inf")

    equity = 0; peak = 0; max_dd = 0
    for p in pnls:
        equity += p
        if equity > peak: peak = equity
        dd = peak - equity
        if dd > max_dd: max_dd = dd

    # Compound: $100 start
    acct = 100.0
    for p in pnls:
        acct *= (1 + p / 100)

    return {
        "label":         label,
        "total_trades":  len(trades),
        "wins":          len(wins),
        "break_even":    len(be),
        "losses":        len(losses),
        "win_rate":      round(win_rate, 1),
        "avg_win_pct":   round(avg_win, 3),
        "avg_loss_pct":  round(avg_loss, 3),
        "profit_factor": round(pf, 2),
        "total_pnl_pct": round(sum(pnls), 3),
        "max_drawdown":  round(max_dd, 3),
        "final_$100":    round(acct, 2),
    }


def run_backtest(symbols: list[str], days: int, partial_tp: bool = True):
    print(f"\n=== Crypto Backtest: {', '.join(symbols)} — {days} days ===")
    print(f"Partial TP: {'ON' if partial_tp else 'OFF'}\n")

    all_trades = []; train_trades = []; test_trades = []

    for symbol in symbols:
        print(f"Fetching {symbol}...")
        try:
            h1  = fetch_crypto(symbol, "1H",    days=max(days, 14))
            m15 = fetch_crypto(symbol, "15Min",  days=days)
        except Exception as e:
            print(f"  Error fetching {symbol}: {e}")
            continue

        split = int(len(m15) * TRAIN_SPLIT)
        m15_train = m15.iloc[:split]
        m15_test  = m15.iloc[split:]
        h1_split  = int(len(h1) * TRAIN_SPLIT)
        h1_train  = h1.iloc[:h1_split]
        h1_test   = h1.iloc[h1_split:]

        print(f"  {symbol}: {len(h1)} 1H bars | {len(m15)} 15Min bars")
        print(f"  Train: {len(m15_train)} | Test: {len(m15_test)}")

        train = simulate_crypto(symbol, h1_train, m15_train, partial_tp)
        test  = simulate_crypto(symbol, h1_test,  m15_test,  partial_tp)

        print(f"  Train trades: {len(train)} | Test trades: {len(test)}")
        train_trades.extend(train)
        test_trades.extend(test)
        all_trades.extend(train + test)

    print("\n" + "=" * 60)
    train_m = compute_metrics(train_trades, "TRAIN")
    test_m  = compute_metrics(test_trades,  "TEST (out-of-sample)")
    total_m = compute_metrics(all_trades,   "TOTAL")

    for m in [train_m, test_m, total_m]:
        print(f"\n{m['label']}")
        print(f"  Trades: {m.get('total_trades',0)} | Wins: {m.get('wins',0)} | BE: {m.get('break_even',0)} | Losses: {m.get('losses',0)}")
        print(f"  Win Rate: {m.get('win_rate',0)}% | PF: {m.get('profit_factor',0)}")
        print(f"  Total P&L: {m.get('total_pnl_pct',0)}% | $100 → ${m.get('final_$100',100)}")
        print(f"  Max Drawdown: {m.get('max_drawdown',0)}%")

    out = {
        "date": str(datetime.utcnow().date()),
        "symbols": symbols, "days": days, "partial_tp": partial_tp,
        "train": train_m, "test": test_m, "total": total_m,
        "trades": all_trades,
    }
    path = RESULTS_DIR / f"crypto_backtest_{datetime.utcnow().date()}_{days}d.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"\n[crypto_bt] Saved to {path}")
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=config.CRYPTO_SYMBOLS)
    parser.add_argument("--days",    type=int,  default=30)
    parser.add_argument("--no-partial-tp", action="store_true")
    args = parser.parse_args()
    run_backtest(args.symbols, args.days, partial_tp=not args.no_partial_tp)
