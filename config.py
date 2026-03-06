import os
from dotenv import load_dotenv

load_dotenv()

# Alpaca — paper trading only
ALPACA_API_KEY    = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL   = "https://paper-api.alpaca.markets"  # never change this

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# Anthropic (for automated analysis feedback)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Strategy
SYMBOLS            = [s.strip() for s in os.getenv("SYMBOLS", "SPY,QQQ").split(",")]
DAILY_LOSS_LIMIT   = float(os.getenv("DAILY_LOSS_LIMIT_PCT", "3.0"))   # percent
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "1.0"))     # percent
RR_RATIO           = float(os.getenv("RR_RATIO", "2.0"))
STOP_LOSS_PCT      = float(os.getenv("STOP_LOSS_PCT", "0.5"))

# Timeframes
M1_TIMEFRAME = "1Min"
M5_TIMEFRAME = "5Min"

# Market hours (ET)
MARKET_OPEN_ET  = "09:30"
MARKET_CLOSE_ET = "15:55"  # stop 5 min early to avoid close chaos

def validate():
    missing = [k for k, v in {
        "ALPACA_API_KEY": ALPACA_API_KEY,
        "ALPACA_SECRET_KEY": ALPACA_SECRET_KEY,
        "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
        "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
    }.items() if not v]
    if missing:
        raise EnvironmentError(f"Missing required config: {missing}")
