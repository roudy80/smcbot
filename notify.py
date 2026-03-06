"""
Telegram notifications — your phone IS the dashboard.
Every significant event fires a message here.
"""

import requests
from datetime import datetime

import config


def _send(text: str):
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print(f"[notify] (Telegram not configured) {text}")
        return
    url  = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": config.TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=data, timeout=5)
    except Exception as e:
        print(f"[notify] Telegram error: {e}")


def signal_detected(signal):
    _send(
        f"*SIGNAL* {signal.direction.upper()} `{signal.symbol}`\n"
        f"Entry: `{signal.entry}` | SL: `{signal.stop_loss}` | TP: `{signal.take_profit}`\n"
        f"FVG: `{signal.fvg_bot}` - `{signal.fvg_top}` | MSS: `{signal.mss_level}`\n"
        f"Time: {signal.timestamp.strftime('%H:%M:%S ET')}"
    )


def order_placed(symbol: str, direction: str, qty: int, entry: float, sl: float, tp: float):
    _send(
        f"*ORDER PLACED* {direction.upper()} `{symbol}`\n"
        f"Qty: {qty} | Entry: `{entry}` | SL: `{sl}` | TP: `{tp}`"
    )


def order_filled(symbol: str, direction: str, fill_price: float, qty: int):
    _send(
        f"*FILLED* {direction.upper()} `{symbol}`\n"
        f"Qty: {qty} @ `{fill_price}`"
    )


def trade_closed(symbol: str, direction: str, pnl: float, outcome: str):
    emoji = "+" if pnl >= 0 else "-"
    _send(
        f"*CLOSED* {direction.upper()} `{symbol}` — {outcome}\n"
        f"P&L: `{emoji}${abs(pnl):.2f}`"
    )


def kill_switch_fired(account_value: float, daily_loss_pct: float):
    _send(
        f"*KILL SWITCH FIRED*\n"
        f"Daily loss: `{daily_loss_pct:.2f}%`\n"
        f"Account value: `${account_value:.2f}`\n"
        f"All trading halted until tomorrow. All positions closed."
    )


def daily_summary(stats: dict):
    pnl_str = f"+${stats['pnl']:.2f}" if stats["pnl"] >= 0 else f"-${abs(stats['pnl']):.2f}"
    _send(
        f"*DAILY SUMMARY* {datetime.now().strftime('%Y-%m-%d')}\n"
        f"Trades: {stats['trades']} | Wins: {stats['wins']} | Losses: {stats['losses']}\n"
        f"Win Rate: {stats.get('win_rate', 0):.1f}% | P&L: `{pnl_str}`\n"
        f"Account: `${stats['account_value']:.2f}`"
    )


def bot_started(symbols: list[str]):
    _send(f"*BOT STARTED*\nWatching: `{', '.join(symbols)}`\nPaper trading mode.")


def error_alert(msg: str):
    _send(f"*ERROR*\n`{msg}`")
