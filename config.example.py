# Copy this to .env and fill in your values. Never commit .env to git.

# Alpaca Paper Trading (https://app.alpaca.markets -> create paper account)
ALPACA_API_KEY=your_paper_api_key_here
ALPACA_SECRET_KEY=your_paper_secret_key_here

# Telegram Bot (create via @BotFather on Telegram)
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# Anthropic API (for automated performance analysis)
ANTHROPIC_API_KEY=your_anthropic_key_here

# Strategy settings
SYMBOLS=SPY,QQQ,AAPL          # comma-separated watchlist
DAILY_LOSS_LIMIT_PCT=3.0       # kill switch threshold (% of account)
RISK_PER_TRADE_PCT=1.0         # risk per trade (% of account)
RR_RATIO=2.0                   # take profit = stop_loss * this
STOP_LOSS_PCT=0.5              # hard stop distance from entry (%)
