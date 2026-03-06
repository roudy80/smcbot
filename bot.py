"""
Main bot entry point — fully autonomous paper trading.

Flow:
  1. Validate config, initialize Alpaca paper account
  2. Seed M5 + M1 buffers with recent historical data
  3. Open WebSocket stream for live bar updates
  4. On each closed M1 bar: check kill switch → run signal → place bracket order
  5. TradingStream monitors fills and order updates automatically
  6. At market close: run analyze.py, send daily summary to Telegram
"""

import asyncio
import signal as os_signal
import sys
import threading
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

import pandas as pd
import schedule

import config
import logger
import notify
from analyze import run_analysis
from execution import broker, risk
from feeds.historical import fetch
from feeds.live import LiveFeed
from strategy.signal import generate_signal

ET = ZoneInfo("America/New_York")

# Track M5 data per symbol (seeded from historical, updated live)
m5_buffers: dict[str, pd.DataFrame] = {}

# Deduplicate signals: track last signal time per symbol
last_signal: dict[str, datetime] = {}
SIGNAL_COOLDOWN_MINUTES = 15

# Track active order IDs → signal mapping for logging
active_orders: dict[str, dict] = {}


def is_market_hours() -> bool:
    now = datetime.now(ET).time()
    open_t  = dt_time(9, 30)
    close_t = dt_time(15, 55)
    return open_t <= now <= close_t


def seed_historical_buffers():
    """Pre-load historical M5 and M1 data into buffers before going live."""
    print("[bot] Seeding historical buffers...")
    for symbol in config.SYMBOLS:
        m5_buffers[symbol] = fetch(symbol, config.M5_TIMEFRAME, days=5)
        print(f"[bot] {symbol}: {len(m5_buffers[symbol])} M5 bars loaded")


def on_bar_closed(symbol: str, timeframe: str, df: pd.DataFrame):
    """
    Called by LiveFeed on every closed bar.
    Only act on M1 bars during market hours.
    """
    if timeframe == "5Min":
        # Keep M5 buffer updated for MSS context
        m5_buffers[symbol] = df
        return

    if timeframe != "1Min":
        return

    if not is_market_hours():
        return

    # Check kill switch FIRST
    try:
        account_value = broker.get_account_value()
    except Exception as e:
        print(f"[bot] Could not get account value: {e}")
        return

    if risk.check_kill_switch(account_value):
        return  # already fired, silently skip

    # Cooldown: skip if we signaled this symbol recently
    now = datetime.now(ET)
    last = last_signal.get(symbol)
    if last and (now - last).seconds < SIGNAL_COOLDOWN_MINUTES * 60:
        return

    m5 = m5_buffers.get(symbol)
    if m5 is None or len(m5) < 20:
        return

    if len(df) < 10:
        return

    sig = generate_signal(symbol=symbol, m5_df=m5, m1_df=df)
    if sig is None:
        return

    last_signal[symbol] = now
    notify.signal_detected(sig)

    # Position size
    sl_distance = abs(sig.entry - sig.stop_loss)
    qty = risk.position_size(account_value, sig.entry, sig.stop_loss)

    try:
        order = broker.place_bracket_order(sig, qty)
        order_id = str(order.id)
        active_orders[order_id] = {
            "signal":    sig,
            "qty":       qty,
            "direction": sig.direction,
            "symbol":    symbol,
        }
        logger.log_signal(sig, qty, order_id)
        notify.order_placed(symbol, sig.direction, qty, sig.entry, sig.stop_loss, sig.take_profit)
        print(f"[bot] Order placed: {order_id} {sig.direction} {symbol} x{qty}")
    except Exception as e:
        notify.error_alert(f"Order failed {symbol}: {e}")
        print(f"[bot] Order error: {e}")


def end_of_day_tasks():
    """Run at 4PM ET: summarize, analyze, reset."""
    if not is_market_hours():
        return

    print("[bot] End of day — running analysis...")

    # Close any open positions
    try:
        broker.close_all_positions()
        broker.cancel_all_orders()
    except Exception as e:
        print(f"[bot] EOD close error: {e}")

    # Compute and send daily summary
    try:
        account_value = broker.get_account_value()
        from logger import load_all
        records = load_all()
        trades  = [r for r in records if r["event"] == "close"]
        wins    = [t for t in trades if t["outcome"] == "win"]
        losses  = [t for t in trades if t["outcome"] == "loss"]
        notify.daily_summary({
            "trades":        len(trades),
            "wins":          len(wins),
            "losses":        len(losses),
            "win_rate":      len(wins) / len(trades) * 100 if trades else 0,
            "pnl":           sum(t["pnl"] for t in trades),
            "account_value": account_value,
        })
    except Exception as e:
        print(f"[bot] Summary error: {e}")

    # Run Claude analysis if API key is set
    if config.ANTHROPIC_API_KEY:
        try:
            run_analysis(post_to_telegram=True)
        except Exception as e:
            print(f"[bot] Analysis error: {e}")


def run_scheduler():
    """Runs in a background thread to handle scheduled tasks."""
    schedule.every().day.at("16:00").do(end_of_day_tasks)
    while True:
        schedule.run_pending()
        import time; time.sleep(30)


def main():
    print("[bot] Starting SMC Paper Trading Bot")
    config.validate()

    # Initialize
    account_value = broker.get_account_value()
    risk.init_daily_tracker(account_value)
    print(f"[bot] Paper account value: ${account_value:.2f}")

    seed_historical_buffers()
    notify.bot_started(config.SYMBOLS)

    # Background scheduler (EOD tasks, etc.)
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    # Graceful shutdown
    def shutdown(sig, frame):
        print("\n[bot] Shutting down...")
        notify._send("*BOT STOPPED* — manual shutdown")
        sys.exit(0)

    os_signal.signal(os_signal.SIGINT,  shutdown)
    os_signal.signal(os_signal.SIGTERM, shutdown)

    # Start live feed (blocking)
    feed = LiveFeed(on_bar_closed=on_bar_closed)
    feed.run()


if __name__ == "__main__":
    main()
