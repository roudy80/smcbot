"""
Crypto paper trading bot — runs 24/7 alongside bot.py.
Same FVG+MSS strategy, applied to BTC/USD and ETH/USD.
Uses Alpaca's FREE crypto data feed.
Trades from the same paper account, tracked separately in logs/crypto_trades.jsonl.

Run: python crypto_bot.py
"""

import json
import signal as os_signal
import sys
import threading
import time
from datetime import datetime, date
from pathlib import Path

import pandas as pd
import schedule

import config
import notify
from feeds.crypto import CryptoFeed, fetch_crypto
from execution.crypto_broker import (
    get_account_value, crypto_position_size, place_crypto_bracket,
    close_crypto_positions, get_client as get_crypto_client,
)
from execution.position_monitor import PositionMonitor
from strategy.signal import generate_signal
from execution.risk import check_kill_switch, init_daily_tracker, is_killed

CRYPTO_LOG = Path("logs/crypto_trades.jsonl")
CRYPTO_LOG.parent.mkdir(exist_ok=True)

# Buffers per symbol
m5_buffers: dict[str, pd.DataFrame] = {}
m1_buffers: dict[str, pd.DataFrame] = {}
last_signal: dict[str, datetime]    = {}
COOLDOWN_SECONDS = 3600  # 1 hour between signals (crypto needs patience)

# Crypto-specific risk params (wider than stocks — BTC moves 1-2% routinely)
CRYPTO_SL_PCT = 1.5   # 1.5% stop loss vs 0.5% for stocks
CRYPTO_RR     = 2.0   # keep 1:2 RR

_monitor = PositionMonitor(
    get_client_fn=get_crypto_client,
    notify_fn=notify._send,
    label="crypto-monitor",
)


def log(record: dict):
    with open(CRYPTO_LOG, "a") as f:
        f.write(json.dumps(record) + "\n")


def load_crypto_logs() -> list[dict]:
    if not CRYPTO_LOG.exists(): return []
    return [json.loads(l) for l in CRYPTO_LOG.read_text().strip().split("\n") if l.strip()]


def on_bar_closed(symbol: str, timeframe: str, df: pd.DataFrame):
    # Crypto uses 1H for trend (MSS) + 15Min for entry (FVG)
    # Much less noise than 1Min/5Min on BTC/ETH
    if timeframe == "1H":
        m5_buffers[symbol] = df   # reuse m5_buffers for 1H trend data
        return
    if timeframe == "15Min":
        m1_buffers[symbol] = df   # reuse m1_buffers for 15Min entry data

    if timeframe != "15Min":
        return

    # Kill switch check
    try:
        account_value = get_account_value()
    except Exception as e:
        print(f"[crypto] account error: {e}")
        return

    if is_killed():
        return

    # Cooldown
    now  = datetime.utcnow()
    last = last_signal.get(symbol)
    if last and (now - last).seconds < COOLDOWN_SECONDS:
        return

    m5 = m5_buffers.get(symbol)
    m1 = m1_buffers.get(symbol)
    if m5 is None or len(m5) < 20 or m1 is None or len(m1) < 15:
        return

    sig = generate_signal(
        symbol=symbol, m5_df=m5, m1_df=m1,
        mss_lookback=50, fvg_lookback=20, swing_length=5,
        min_gap_pct=0.10,  # higher bar for crypto FVG quality
    )
    if sig is None:
        return

    last_signal[symbol] = now
    notify.signal_detected(sig)
    print(f"[crypto] Signal: {sig.direction.upper()} {symbol} @ {sig.entry}")

    notional = crypto_position_size(account_value, sig.entry, sig.stop_loss)
    if notional < 1.0:
        print(f"[crypto] Notional too small (${notional:.2f}), skipping")
        return

    try:
        order = place_crypto_bracket(sig, notional)
        log({
            "event": "signal", "ts": now.isoformat(),
            "symbol": symbol, "direction": sig.direction,
            "entry": sig.entry, "stop_loss": sig.stop_loss,
            "take_profit": sig.take_profit, "notional": notional,
            "order_id": str(order.id),
        })
        notify.order_placed(symbol, sig.direction, f"${notional:.0f} notional",
                            sig.entry, sig.stop_loss, sig.take_profit)
        _monitor.track(symbol.replace("/", ""), sig.entry, sig.stop_loss,
                       sig.take_profit, notional, sig.direction)
    except Exception as e:
        print(f"[crypto] Order failed {symbol}: {e}")
        notify.error_alert(f"Crypto order failed {symbol}: {e}")


def send_crypto_summary():
    records = load_crypto_logs()
    trades  = [r for r in records if r["event"] == "close"]
    signals = [r for r in records if r["event"] == "signal"]
    wins    = [t for t in trades if t.get("outcome") == "win"]
    losses  = [t for t in trades if t.get("outcome") == "loss"]
    pnl     = sum(t.get("pnl", 0) for t in trades)
    notify._send(
        f"*CRYPTO DAILY SUMMARY* {date.today()}\n"
        f"Signals: {len(signals)} | Trades: {len(trades)}\n"
        f"Wins: {len(wins)} | Losses: {len(losses)}\n"
        f"P&L: `{'+'if pnl>=0 else ''}${pnl:.2f}`"
    )


def run_scheduler():
    schedule.every().day.at("23:55").do(send_crypto_summary)
    while True:
        schedule.run_pending()
        time.sleep(60)


def seed_buffers():
    print("[crypto] Seeding historical buffers (1H trend + 15Min entry)...")
    for symbol in config.CRYPTO_SYMBOLS:
        try:
            m5_buffers[symbol] = fetch_crypto(symbol, "1H",   days=14)
            m1_buffers[symbol] = fetch_crypto(symbol, "15Min", days=3)
            print(f"[crypto] {symbol}: {len(m5_buffers[symbol])} 1H bars, "
                  f"{len(m1_buffers[symbol])} 15Min bars")
        except Exception as e:
            print(f"[crypto] seed error {symbol}: {e}")


def main():
    print("[crypto] Starting Crypto Paper Trading Bot")
    print(f"[crypto] Symbols: {config.CRYPTO_SYMBOLS}")
    print(f"[crypto] Allocation: {config.CRYPTO_ALLOC_PCT}% of account")

    account_value = get_account_value()
    alloc = account_value * config.CRYPTO_ALLOC_PCT / 100
    print(f"[crypto] Paper account: ${account_value:,.2f} | Crypto allocation: ${alloc:,.2f}")

    init_daily_tracker(account_value)
    seed_buffers()

    notify._send(
        f"*CRYPTO BOT STARTED*\n"
        f"Watching: `{'  '.join(config.CRYPTO_SYMBOLS)}`\n"
        f"Allocation: `${alloc:,.0f}` ({config.CRYPTO_ALLOC_PCT}% of account)\n"
        f"Runs 24/7 — signals anytime"
    )

    threading.Thread(target=run_scheduler, daemon=True).start()
    _monitor.start()

    def shutdown(sig, frame):
        print("\n[crypto] Shutting down...")
        notify._send("*CRYPTO BOT STOPPED*")
        sys.exit(0)

    os_signal.signal(os_signal.SIGINT,  shutdown)
    os_signal.signal(os_signal.SIGTERM, shutdown)

    feed = CryptoFeed(symbols=config.CRYPTO_SYMBOLS, on_bar_closed=on_bar_closed)
    feed.run()  # blocking


if __name__ == "__main__":
    main()
