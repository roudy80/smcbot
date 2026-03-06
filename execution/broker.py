"""
Alpaca paper trading wrapper.
Uses bracket orders so Alpaca handles SL/TP automatically — no monitoring loop needed.
"""

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    TakeProfitRequest,
    StopLossRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass

import config
from strategy.signal import Signal

_client: TradingClient | None = None


def get_client() -> TradingClient:
    global _client
    if _client is None:
        _client = TradingClient(
            api_key    = config.ALPACA_API_KEY,
            secret_key = config.ALPACA_SECRET_KEY,
            paper      = True,   # HARD-CODED: paper only
        )
    return _client


def get_account_value() -> float:
    acct = get_client().get_account()
    return float(acct.portfolio_value)


def place_bracket_order(signal: Signal, qty: int) -> dict:
    """
    Submit a bracket order (entry + SL + TP in one request).
    Alpaca manages the SL/TP legs automatically after fill.

    Returns the order object as a dict.
    """
    client = get_client()
    side   = OrderSide.BUY if signal.direction == "long" else OrderSide.SELL

    req = LimitOrderRequest(
        symbol        = signal.symbol,
        qty           = qty,
        side          = side,
        time_in_force = TimeInForce.DAY,
        limit_price   = round(signal.entry, 2),
        order_class   = OrderClass.BRACKET,
        take_profit   = TakeProfitRequest(limit_price=round(signal.take_profit, 2)),
        stop_loss     = StopLossRequest(stop_price=round(signal.stop_loss, 2)),
    )

    order = client.submit_order(req)
    return order


def cancel_all_orders():
    get_client().cancel_orders()


def get_open_positions() -> list:
    return get_client().get_all_positions()


def close_all_positions():
    get_client().close_all_positions(cancel_orders=True)
