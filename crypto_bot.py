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
    get_account_value, crypto_position_size, place_crypto_bracket, close_crypto_positions
)
from strategy.signal import generate_signal
from execution.risk import check_kill_switch, init_daily_tracker, is_killed

CRYPTO_LOG = Path("logs/crypto_trades.jsonl")
CRYPTO_LOG.parent.mkdir(exist_ok=True)

# Buffers per symbol
m5_buffers: dict[str, pd.DataFrame] = {}
m1_buffers: dict[str, pd.DataFrame] = {}
last_signal: dict[str, datetime]    = {}
COOLDOWN_SECONDS = 600  # 10 minutes between signals per symbol


def log(record: dict):
    with open(CRYPTO_LOG, "a") as f:
        f.write(json.dumps(record) + "\n")


def load_crypto_logs() -> list[dict]:
    if not CRYPTO_LOG.exists(): return []
    return [json.loads(l) for l in CRYPTO_LOG.read_text().strip().split("\n") if l.strip()]


def on_bar_closed(symbol: str, timeframe: str, df: pd.DataFrame):
    if timeframe == "5Min":
        m5_buffers[symbol] = df
        return
    if timeframe == "1Min":
        m1_buffers[symbol] = df

    if timeframe != "1Min":
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
        mss_lookback=50, fvg_lookback=30, swing_length=7,
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
    print("[crypto] Seeding historical buffers...")
    for symbol in config.CRYPTO_SYMBOLS:
        try:
            m5_buffers[symbol] = fetch_crypto(symbol, "5Min", days=5)
            m1_buffers[symbol] = fetch_crypto(symbol, "1Min", days=1)
            print(f"[crypto] {symbol}: {len(m5_buffers[symbol])} M5 bars, "
                  f"{len(m1_buffers[symbol])} M1 bars")
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
