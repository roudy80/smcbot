"""
Structured trade logger. Writes every signal and trade outcome to
logs/trades.jsonl (newline-delimited JSON) for analysis and Claude feedback.
"""

import json
from datetime import datetime
from pathlib import Path

LOG_FILE = Path("logs/trades.jsonl")


def _append(record: dict):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")


def log_signal(signal, qty: int, order_id: str):
    _append({
        "event":       "signal",
        "ts":          datetime.utcnow().isoformat(),
        "symbol":      signal.symbol,
        "direction":   signal.direction,
        "entry":       signal.entry,
        "stop_loss":   signal.stop_loss,
        "take_profit": signal.take_profit,
        "fvg_top":     signal.fvg_top,
        "fvg_bot":     signal.fvg_bot,
        "mss_level":   signal.mss_level,
        "qty":         qty,
        "order_id":    order_id,
    })


def log_fill(order_id: str, symbol: str, fill_price: float, qty: int):
    _append({
        "event":      "fill",
        "ts":         datetime.utcnow().isoformat(),
        "order_id":   order_id,
        "symbol":     symbol,
        "fill_price": fill_price,
        "qty":        qty,
    })


def log_close(order_id: str, symbol: str, pnl: float, outcome: str, reason: str):
    _append({
        "event":    "close",
        "ts":       datetime.utcnow().isoformat(),
        "order_id": order_id,
        "symbol":   symbol,
        "pnl":      pnl,
        "outcome":  outcome,  # "win" | "loss" | "break_even"
        "reason":   reason,   # "take_profit" | "stop_loss" | "kill_switch" | "eod"
    })


def log_kill_switch(account_value: float, daily_loss_pct: float):
    _append({
        "event":          "kill_switch",
        "ts":             datetime.utcnow().isoformat(),
        "account_value":  account_value,
        "daily_loss_pct": daily_loss_pct,
    })


def load_all() -> list[dict]:
    if not LOG_FILE.exists():
        return []
    with open(LOG_FILE) as f:
        return [json.loads(line) for line in f if line.strip()]
