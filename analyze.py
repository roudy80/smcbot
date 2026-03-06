"""
Automated performance analysis using the Claude API.

Reads logs/trades.jsonl, computes performance metrics, sends them to Claude,
gets back specific improvement suggestions, saves the report to
logs/analysis/YYYY-MM-DD.md, and optionally posts to Telegram.

Run manually:   python analyze.py
Run on schedule: called by bot.py at market close each day.
"""

import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import anthropic

import config
import notify
from logger import load_all

ANALYSIS_DIR = Path("logs/analysis")
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)


def compute_metrics(records: list[dict]) -> dict:
    trades   = [r for r in records if r["event"] == "close"]
    signals  = [r for r in records if r["event"] == "signal"]

    wins   = [t for t in trades if t["outcome"] == "win"]
    losses = [t for t in trades if t["outcome"] == "loss"]

    pnl_list    = [t["pnl"] for t in trades]
    total_pnl   = sum(pnl_list)
    win_rate    = len(wins) / len(trades) * 100 if trades else 0

    # Average RR on wins vs losses
    avg_win  = sum(t["pnl"] for t in wins)  / len(wins)  if wins   else 0
    avg_loss = sum(t["pnl"] for t in losses) / len(losses) if losses else 0

    # Profit factor
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss   = abs(sum(t["pnl"] for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss else float("inf")

    # Max drawdown (running)
    peak   = 0
    trough = 0
    running_pnl = 0
    max_dd = 0
    for pnl in pnl_list:
        running_pnl += pnl
        if running_pnl > peak:
            peak = running_pnl
        dd = peak - running_pnl
        if dd > max_dd:
            max_dd = dd

    # Signal → fill rate (how many signals actually got filled)
    fills = [r for r in records if r["event"] == "fill"]

    # Per-symbol breakdown
    by_symbol = defaultdict(lambda: {"trades": 0, "pnl": 0, "wins": 0})
    for t in trades:
        by_symbol[t["symbol"]]["trades"] += 1
        by_symbol[t["symbol"]]["pnl"]    += t["pnl"]
        by_symbol[t["symbol"]]["wins"]   += 1 if t["outcome"] == "win" else 0

    return {
        "total_trades":   len(trades),
        "total_signals":  len(signals),
        "fill_rate":      len(fills) / len(signals) * 100 if signals else 0,
        "wins":           len(wins),
        "losses":         len(losses),
        "win_rate":       round(win_rate, 1),
        "total_pnl":      round(total_pnl, 2),
        "avg_win":        round(avg_win, 2),
        "avg_loss":       round(avg_loss, 2),
        "profit_factor":  round(profit_factor, 2),
        "max_drawdown":   round(max_dd, 2),
        "by_symbol":      dict(by_symbol),
    }


def run_analysis(post_to_telegram: bool = True) -> str:
    records = load_all()
    if not records:
        return "No trade data available yet."

    metrics = compute_metrics(records)

    # Build prompt for Claude
    prompt = f"""You are reviewing the performance of an automated paper trading bot that trades
Smart Money Concepts (SMC) Fair Value Gaps (FVG) with Market Structure Shift (MSS) confirmation
on US equities using Alpaca paper trading. Here are the current performance metrics:

{json.dumps(metrics, indent=2)}

Strategy parameters:
- Entry: M1 FVG with M5 MSS confirmation
- Stop loss: {config.STOP_LOSS_PCT}% from entry
- Take profit: {config.RR_RATIO}:1 Risk-to-Reward
- Daily kill switch: {config.DAILY_LOSS_LIMIT}% max daily loss
- Symbols traded: {config.SYMBOLS}

Please analyze these results and provide:
1. An honest assessment of whether the strategy is performing as expected
2. The 2-3 most impactful specific parameter changes to test next (with exact values)
3. Any red flags in the data that suggest overfitting, slippage issues, or signal quality problems
4. A recommended next experiment to run in backtest.py before changing live parameters

Be specific and quantitative. Do not suggest generic improvements like "improve risk management"."""

    client   = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model      = "claude-sonnet-4-6",
        max_tokens = 1024,
        messages   = [{"role": "user", "content": prompt}],
    )
    analysis = response.content[0].text

    # Save report
    report_path = ANALYSIS_DIR / f"{date.today()}.md"
    report = f"# SMC Bot Analysis — {date.today()}\n\n## Metrics\n```json\n{json.dumps(metrics, indent=2)}\n```\n\n## Claude Analysis\n\n{analysis}\n"
    report_path.write_text(report)
    print(f"[analyze] Report saved to {report_path}")

    # Post summary to Telegram
    if post_to_telegram:
        summary = (
            f"*DAILY ANALYSIS*\n"
            f"Trades: {metrics['total_trades']} | WR: {metrics['win_rate']}% | "
            f"PF: {metrics['profit_factor']} | P&L: ${metrics['total_pnl']}\n\n"
            f"_See logs/analysis/{date.today()}.md for full report_"
        )
        notify._send(summary)

    return analysis


if __name__ == "__main__":
    print(run_analysis(post_to_telegram=False))
