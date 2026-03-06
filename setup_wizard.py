"""
SMC Bot Setup Wizard
Run this once: python setup_wizard.py
It walks you through every API key, tests each connection, and saves your config.
"""

import os
import sys
import requests
from pathlib import Path

ENV_FILE = Path(".env")

BANNER = """
╔══════════════════════════════════════════╗
║        SMC BOT — SETUP WIZARD           ║
╚══════════════════════════════════════════╝
This will walk you through getting and
entering each API key. Takes ~5 minutes.
"""

def ask(prompt, secret=False):
    val = input(f"\n{prompt}\n> ").strip()
    return val

def section(title):
    print(f"\n{'─'*44}")
    print(f"  {title}")
    print(f"{'─'*44}")

def ok(msg):   print(f"  ✓  {msg}")
def err(msg):  print(f"  ✗  {msg}")
def info(msg): print(f"  →  {msg}")


# ── Alpaca ──────────────────────────────────────────────────────────────────

def get_alpaca_keys():
    section("STEP 1 OF 3 — Alpaca Paper Trading (free)")
    print("""
  1. Go to:  app.alpaca.markets
  2. Sign up for a free account
  3. In the left sidebar click "Paper Trading"
  4. Click the "Generate New Key" button
  5. Copy both keys below
""")
    api_key    = ask("Paste your Alpaca API Key ID:")
    secret_key = ask("Paste your Alpaca Secret Key:")

    # Test the connection
    info("Testing Alpaca connection...")
    try:
        headers = {
            "APCA-API-KEY-ID":     api_key,
            "APCA-API-SECRET-KEY": secret_key,
        }
        r = requests.get(
            "https://paper-api.alpaca.markets/v2/account",
            headers=headers, timeout=8
        )
        if r.status_code == 200:
            data = r.json()
            ok(f"Connected! Paper account value: ${float(data['portfolio_value']):,.2f}")
            return api_key, secret_key
        else:
            err(f"Connection failed (status {r.status_code}) — double-check your keys")
            retry = input("  Try again? (y/n): ").strip().lower()
            if retry == "y":
                return get_alpaca_keys()
            sys.exit(1)
    except Exception as e:
        err(f"Could not connect: {e}")
        sys.exit(1)


# ── Telegram ─────────────────────────────────────────────────────────────────

def get_telegram_keys():
    section("STEP 2 OF 3 — Telegram (phone alerts)")
    print("""
  Getting your Bot Token:
  1. Open Telegram on your phone
  2. Search for @BotFather
  3. Tap START, then send:  /newbot
  4. Pick any name (e.g. "My SMC Bot")
  5. Pick any username ending in 'bot' (e.g. "mysmc_bot")
  6. BotFather sends you a token like:  7123456789:AAFxxx...
""")
    token = ask("Paste your Bot Token:")

    print("""
  Getting your Chat ID:
  1. In Telegram, search for @userinfobot
  2. Tap START or send any message
  3. It replies with your ID (just a number like 123456789)
""")
    chat_id = ask("Paste your Chat ID:")

    # Test by sending a message
    info("Sending test message to your Telegram...")
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": "SMC Bot connected! Setup complete."},
            timeout=8
        )
        if r.status_code == 200:
            ok("Message sent — check your Telegram!")
            return token, chat_id
        else:
            err(f"Failed (status {r.status_code}) — check token and chat ID")
            retry = input("  Try again? (y/n): ").strip().lower()
            if retry == "y":
                return get_telegram_keys()
            else:
                info("Skipping Telegram — you can add it later")
                return "", ""
    except Exception as e:
        err(f"Could not reach Telegram: {e}")
        info("Skipping — add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to .env later")
        return "", ""


# ── Anthropic ────────────────────────────────────────────────────────────────

def get_anthropic_key():
    section("STEP 3 OF 3 — Anthropic API (daily AI analysis)")
    print("""
  This lets the bot analyze its own trades every night and
  send you improvement suggestions. Optional but recommended.

  1. Go to:  console.anthropic.com
  2. Sign up (free $5 credit included)
  3. Click "API Keys" → "Create Key"
""")
    skip = input("  Skip for now? (y/n): ").strip().lower()
    if skip == "y":
        info("Skipping — add ANTHROPIC_API_KEY to .env later")
        return ""

    key = ask("Paste your Anthropic API Key:")

    info("Testing Anthropic connection...")
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": "hi"}]
        )
        ok("Anthropic connected!")
        return key
    except Exception as e:
        err(f"Could not connect: {e}")
        info("Key saved anyway — verify it later")
        return key


# ── Strategy Settings ────────────────────────────────────────────────────────

def get_strategy_settings():
    section("STRATEGY SETTINGS (press Enter to keep defaults)")
    print()

    defaults = {
        "SYMBOLS":              ("SPY,QQQ", "Symbols to trade (comma separated)"),
        "DAILY_LOSS_LIMIT_PCT": ("3.0",     "Kill switch: max daily loss %"),
        "RISK_PER_TRADE_PCT":   ("1.0",     "Risk per trade % of account"),
        "RR_RATIO":             ("2.0",     "Take profit = stop loss × this"),
        "STOP_LOSS_PCT":        ("0.5",     "Stop loss distance from entry %"),
    }

    values = {}
    for key, (default, desc) in defaults.items():
        val = input(f"  {desc} [{default}]: ").strip()
        values[key] = val if val else default

    return values


# ── Write .env ───────────────────────────────────────────────────────────────

def write_env(alpaca_key, alpaca_secret, tg_token, tg_chat, anthropic_key, strategy):
    lines = [
        "# SMC Bot Configuration — DO NOT commit this file to git\n",
        f"ALPACA_API_KEY={alpaca_key}\n",
        f"ALPACA_SECRET_KEY={alpaca_secret}\n",
        f"TELEGRAM_BOT_TOKEN={tg_token}\n",
        f"TELEGRAM_CHAT_ID={tg_chat}\n",
        f"ANTHROPIC_API_KEY={anthropic_key}\n",
        "\n",
    ]
    for k, v in strategy.items():
        lines.append(f"{k}={v}\n")

    ENV_FILE.write_text("".join(lines))
    ok(f"Saved to {ENV_FILE.resolve()}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(BANNER)

    if ENV_FILE.exists():
        overwrite = input("  .env already exists. Overwrite? (y/n): ").strip().lower()
        if overwrite != "y":
            print("  Cancelled.")
            sys.exit(0)

    alpaca_key, alpaca_secret = get_alpaca_keys()
    tg_token, tg_chat         = get_telegram_keys()
    anthropic_key             = get_anthropic_key()
    strategy                  = get_strategy_settings()

    section("SAVING CONFIG")
    write_env(alpaca_key, alpaca_secret, tg_token, tg_chat, anthropic_key, strategy)

    print(f"""
╔══════════════════════════════════════════╗
║           SETUP COMPLETE!               ║
╚══════════════════════════════════════════╝

  Next steps:

  Run a backtest (no real money, uses history):
    python backtest.py

  Start the live paper trading bot:
    python bot.py

  Run the AI analysis on your trade log:
    python analyze.py
""")


if __name__ == "__main__":
    main()
