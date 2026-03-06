"""
Partial take-profit & break-even stop manager.

Runs as a background thread, checking positions every 60s.
When a position reaches halfway to target (1R), takes 50% off and
moves stop to break-even on the remaining half.
"""

import time
import threading

from alpaca.trading.requests import MarketOrderRequest, StopOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce


class PositionMonitor:
    def __init__(self, get_client_fn, notify_fn=None, label="monitor"):
        self._get_client = get_client_fn
        self._notify     = notify_fn or (lambda msg: None)
        self._label      = label
        self._managed: dict[str, dict] = {}
        self._running = False

    def track(self, symbol: str, entry: float, stop_loss: float,
              take_profit: float, qty, side: str):
        """Register a position for partial TP monitoring."""
        self._managed[symbol] = {
            "entry":        entry,
            "stop_loss":    stop_loss,
            "take_profit":  take_profit,
            "qty":          qty,
            "side":         side,
            "partial_done": False,
        }
        print(f"[{self._label}] Tracking {symbol} {side} x{qty} "
              f"entry={entry:.4f} sl={stop_loss:.4f} tp={take_profit:.4f}")

    def _check(self):
        client = self._get_client()
        try:
            positions = client.get_all_positions()
        except Exception as e:
            print(f"[{self._label}] Error fetching positions: {e}")
            return

        open_syms = {p.symbol for p in positions}

        # Remove positions that are no longer open
        for sym in list(self._managed.keys()):
            # Crypto: "BTC/USD" → "BTCUSD" on Alpaca side
            alpaca_sym = sym.replace("/", "")
            if alpaca_sym not in open_syms and sym not in open_syms:
                del self._managed[sym]
                continue

        for pos in positions:
            sym = pos.symbol
            # Reverse-map crypto: "BTCUSD" might be tracked as "BTC/USD"
            info = self._managed.get(sym) or self._managed.get(sym[:3] + "/" + sym[3:])
            if info is None or info["partial_done"]:
                continue

            current = float(pos.current_price)
            entry   = info["entry"]
            tp      = info["take_profit"]
            side    = info["side"]

            # Halfway point = 1R (half the distance to full TP)
            if side == "long":
                half_tp = entry + (tp - entry) * 0.5
                reached = current >= half_tp
            else:
                half_tp = entry - (entry - tp) * 0.5
                reached = current <= half_tp

            if not reached:
                continue

            qty      = abs(int(float(pos.qty)))
            half_qty = max(1, qty // 2)
            remaining = qty - half_qty

            try:
                # Cancel open bracket legs for this symbol
                for order in client.get_orders():
                    if order.symbol == sym:
                        try:
                            client.cancel_order_by_id(str(order.id))
                        except Exception:
                            pass

                # Close half at market
                close_side = OrderSide.SELL if side == "long" else OrderSide.BUY
                client.submit_order(MarketOrderRequest(
                    symbol        = sym,
                    qty           = half_qty,
                    side          = close_side,
                    time_in_force = TimeInForce.GTC,
                ))

                # Place break-even stop for remaining shares
                if remaining > 0:
                    client.submit_order(StopOrderRequest(
                        symbol        = sym,
                        qty           = remaining,
                        side          = close_side,
                        time_in_force = TimeInForce.GTC,
                        stop_price    = round(entry, 4),
                    ))

                info["partial_done"] = True
                msg = (f"Partial TP {sym}: closed {half_qty} @ ~{current:.4f}, "
                       f"BE stop @ {entry:.4f} for {remaining} remaining")
                print(f"[{self._label}] {msg}")
                self._notify(msg)

            except Exception as e:
                print(f"[{self._label}] Partial TP error {sym}: {e}")

    def _run(self):
        while self._running:
            self._check()
            time.sleep(60)

    def start(self):
        self._running = True
        t = threading.Thread(target=self._run, daemon=True)
        t.start()
        return t

    def stop(self):
        self._running = False
