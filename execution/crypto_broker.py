"""
Crypto order execution via Alpaca paper trading.
Crypto uses notional (dollar) amounts instead of share quantities.
"""

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, TakeProfitRequest, StopLossRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass

import config
from strategy.signal import Signal

# Crypto allocation: portion of paper account reserved for crypto
CRYPTO_ALLOCATION_PCT = 0.10   # use 10% of account for crypto trades
CRYPTO_RISK_PCT       = 0.02   # risk 2% of crypto allocation per trade

_client = None
def get_client():
    global _client
    if _client is None:
        _client = TradingClient(api_key=config.ALPACA_API_KEY,
                                secret_key=config.ALPACA_SECRET_KEY, paper=True)
    return _client


def get_account_value() -> float:
    return float(get_client().get_account().portfolio_value)


def crypto_position_size(account_value: float, entry: float, stop_loss: float) -> float:
    """
    Returns notional dollar amount to buy (Alpaca crypto uses $ not shares).
    Risk: CRYPTO_RISK_PCT of CRYPTO_ALLOCATION_PCT of account.
    """
    allocation  = account_value * CRYPTO_ALLOCATION_PCT
    risk_dollars = allocation * CRYPTO_RISK_PCT
    sl_pct       = abs(entry - stop_loss) / entry
    if sl_pct == 0:
        return 10.0
    notional = risk_dollars / sl_pct
    return round(min(notional, allocation * 0.5), 2)  # cap at 50% of allocation


def place_crypto_bracket(signal: Signal, notional: float) -> dict:
    """
    Place bracket order for crypto using notional dollar amount.
    Crypto on Alpaca uses TimeInForce.GTC (good till cancelled, trades 24/7).
    """
    client = get_client()
    side   = OrderSide.BUY if signal.direction == "long" else OrderSide.SELL

    # Crypto uses market orders with separate TP/SL as linked orders
    # (Alpaca crypto bracket orders use notional qty)
    req = MarketOrderRequest(
        symbol        = signal.symbol.replace("/", ""),  # "BTC/USD" → "BTCUSD"
        notional      = notional,
        side          = side,
        time_in_force = TimeInForce.GTC,
    )
    order = client.submit_order(req)
    return order


def get_crypto_positions() -> list:
    """Return open crypto positions."""
    all_pos = get_client().get_all_positions()
    crypto  = ["BTC","ETH","SOL","AVAX","LINK"]
    return [p for p in all_pos if any(p.symbol.startswith(c) for c in crypto)]


def close_crypto_positions():
    for p in get_crypto_positions():
        try:
            get_client().close_position(p.symbol)
        except Exception as e:
            print(f"[crypto_broker] close error {p.symbol}: {e}")
