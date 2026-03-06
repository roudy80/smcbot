"""
Risk management: position sizing, daily kill switch.
"""

import json
import os
from datetime import date, datetime
from pathlib import Path

import config

KILL_SWITCH_FILE = Path("logs/kill_switch.json")


def position_size(account_value: float, entry: float, stop_loss: float) -> int:
    """
    Calculate share quantity to risk RISK_PER_TRADE_PCT of account.

    risk_dollars = account_value * risk_pct
    shares = risk_dollars / (entry - stop_loss)
    Returns minimum of 1 share.
    """
    risk_dollars = account_value * (config.RISK_PER_TRADE_PCT / 100)
    sl_distance  = abs(entry - stop_loss)
    if sl_distance == 0:
        return 1
    shares = int(risk_dollars / sl_distance)
    return max(1, shares)


# ---------------------------------------------------------------------------
# Daily Kill Switch
# ---------------------------------------------------------------------------

def _load_kill_state() -> dict:
    if KILL_SWITCH_FILE.exists():
        return json.loads(KILL_SWITCH_FILE.read_text())
    return {"date": str(date.today()), "starting_value": None, "killed": False}


def _save_kill_state(state: dict):
    KILL_SWITCH_FILE.parent.mkdir(parents=True, exist_ok=True)
    KILL_SWITCH_FILE.write_text(json.dumps(state, indent=2))


def init_daily_tracker(account_value: float):
    """
    Call once at bot startup / market open. Records the starting account value
    for today's loss limit calculation.
    """
    state = _load_kill_state()
    today = str(date.today())

    if state["date"] != today:
        # New day: reset
        state = {"date": today, "starting_value": account_value, "killed": False}
    elif state["starting_value"] is None:
        state["starting_value"] = account_value

    _save_kill_state(state)


def is_killed() -> bool:
    """Return True if the daily kill switch has fired."""
    state = _load_kill_state()
    if state["date"] != str(date.today()):
        return False  # stale data from yesterday
    return state.get("killed", False)


def check_kill_switch(current_account_value: float) -> bool:
    """
    Check if daily drawdown has hit the limit.
    Returns True and sets the kill flag if limit breached.
    """
    state = _load_kill_state()
    if state.get("killed"):
        return True

    starting = state.get("starting_value")
    if starting is None or starting == 0:
        return False

    drawdown_pct = (starting - current_account_value) / starting * 100
    if drawdown_pct >= config.DAILY_LOSS_LIMIT:
        state["killed"] = True
        _save_kill_state(state)
        return True

    return False
