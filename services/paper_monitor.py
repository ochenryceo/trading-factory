#!/usr/bin/env python3
"""
Paper Trading Monitor — Track and analyze all 3 strategies during the 1-month paper period.

Reads trades from webhook receiver, computes per-strategy and portfolio metrics,
generates daily/weekly reports, flags concerning behavior.

Start date: 2026-03-25
End date: 2026-04-25 (1 month)
Decision: GO/NO-GO for real money

Strategies:
1. LockedProductionV1 — Mean Reversion (RSI/BB/Vol), Long only, NQ Daily
2. NRG3004C1 — Compression Breakout (ATR/BB/Vol), Long+Short, NQ 1H
3. TFG3003C1 — Trend Following (EMA/ADX), Long only, NQ 1H
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
from collections import defaultdict

log = logging.getLogger("paper_monitor")

PROJECT = Path(__file__).resolve().parents[1]
TRADES_PATH = PROJECT / "data" / "paper_trading" / "trades.json"
REPORT_PATH = PROJECT / "data" / "paper_trading" / "reports"

# Backtest expectations — what we're comparing against
EXPECTATIONS = {
    "LockedProductionV1": {
        "style": "Mean Reversion",
        "direction": "Long only",
        "timeframe": "NQ Daily",
        "expected_wr": 0.57,
        "expected_pf": 2.08,
        "expected_max_dd_pct": 6.0,
        "expected_return_pct": 26.0,
        "notes": "RSI(7)<30 + BB lower + volume. ~26 trades in 16yr backtest.",
    },
    "NRG3004C1": {
        "style": "Compression Breakout",
        "direction": "Long + Short",
        "timeframe": "NQ 1H",
        "expected_wr": 0.50,
        "expected_pf": 1.5,
        "expected_max_dd_pct": 10.0,
        "expected_return_pct": None,
        "notes": "ATR burst + volume spike + BB compression. New strategy, less backtest data.",
    },
    "TFG3003C1": {
        "style": "Trend Following",
        "direction": "Long only",
        "timeframe": "NQ 1H",
        "expected_wr": 0.50,
        "expected_pf": 1.5,
        "expected_max_dd_pct": 10.0,
        "expected_return_pct": None,
        "notes": "EMA(16/55) + ADX(14)>15. Conditional paper candidate. Gini 0.533.",
    },
}

# Alert thresholds
ALERTS = {
    "max_consecutive_losses": 4,
    "max_daily_loss_dollars": 2000,
    "max_drawdown_pct": 15.0,
    "min_win_rate_after_10_trades": 0.30,
}

PAPER_START = datetime(2026, 3, 25, tzinfo=timezone.utc)
PAPER_END = datetime(2026, 4, 25, tzinfo=timezone.utc)


def load_trades() -> List[Dict]:
    """Load all trades from webhook receiver storage."""
    if not TRADES_PATH.exists():
        return []
    try:
        with open(TRADES_PATH) as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except:
        return []


def get_strategy_trades(trades: List[Dict], strategy: str) -> List[Dict]:
    """Filter trades for a specific strategy."""
    return [t for t in trades if t.get("system", t.get("strategy", "")) == strategy]


def compute_metrics(trades: List[Dict]) -> Dict:
    """Compute performance metrics from a list of trades."""
    if not trades:
        return {
            "total_trades": 0, "entries": 0, "exits": 0,
            "completed_trades": 0,
            "wins": 0, "losses": 0, "win_rate": 0.0,
            "total_pnl": 0.0, "avg_pnl": 0.0,
            "max_win": 0.0, "max_loss": 0.0,
            "consecutive_losses": 0, "max_consecutive_losses": 0,
            "profit_factor": 0.0, "peak_pnl": 0.0, "max_drawdown": 0.0,
        }

    entries = [t for t in trades if t.get("action") == "entry"]
    exits = [t for t in trades if t.get("action") == "exit"]
    pnls = [t.get("pnl_dollars", 0) for t in exits if t.get("pnl_dollars", 0) != 0]

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    total_pnl = sum(pnls)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    # Consecutive losses
    max_consec = 0
    current_consec = 0
    for p in pnls:
        if p < 0:
            current_consec += 1
            max_consec = max(max_consec, current_consec)
        else:
            current_consec = 0

    # Drawdown
    equity = 0
    peak = 0
    max_dd = 0
    for p in pnls:
        equity += p
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    return {
        "total_trades": len(trades),
        "entries": len(entries),
        "exits": len(exits),
        "completed_trades": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(pnls) if pnls else 0.0,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(total_pnl / len(pnls), 2) if pnls else 0.0,
        "max_win": round(max(wins), 2) if wins else 0.0,
        "max_loss": round(min(losses), 2) if losses else 0.0,
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else float('inf'),
        "consecutive_losses": current_consec,
        "max_consecutive_losses": max_consec,
        "peak_pnl": round(peak, 2),
        "max_drawdown": round(max_dd, 2),
    }


def check_alerts(strategy: str, metrics: Dict) -> List[str]:
    """Check for concerning behavior."""
    alerts = []

    if metrics["max_consecutive_losses"] >= ALERTS["max_consecutive_losses"]:
        alerts.append(f"⚠️ {strategy}: {metrics['max_consecutive_losses']} consecutive losses (threshold: {ALERTS['max_consecutive_losses']})")

    if metrics["max_drawdown"] >= ALERTS["max_daily_loss_dollars"]:
        alerts.append(f"🔴 {strategy}: Max drawdown ${metrics['max_drawdown']:.0f} exceeds ${ALERTS['max_daily_loss_dollars']}")

    completed = metrics.get("completed_trades", 0)
    if completed >= 10 and metrics["win_rate"] < ALERTS["min_win_rate_after_10_trades"]:
        alerts.append(f"⚠️ {strategy}: Win rate {metrics['win_rate']:.0%} below {ALERTS['min_win_rate_after_10_trades']:.0%} after {completed} trades")

    exp = EXPECTATIONS.get(strategy, {})
    if exp.get("expected_wr") and completed >= 10:
        expected = exp["expected_wr"]
        actual = metrics["win_rate"]
        if actual < expected * 0.7:
            alerts.append(f"⚠️ {strategy}: WR {actual:.0%} significantly below backtest {expected:.0%}")

    return alerts


def generate_report() -> str:
    """Generate a full paper trading report."""
    trades = load_trades()
    now = datetime.now(timezone.utc)
    days_elapsed = (now - PAPER_START).days
    days_remaining = (PAPER_END - now).days

    lines = []
    lines.append("📊 **Paper Trading Report**")
    lines.append(f"Day {days_elapsed}/30 — {days_remaining} days remaining")
    lines.append(f"Period: {PAPER_START.strftime('%b %d')} → {PAPER_END.strftime('%b %d, %Y')}")
    lines.append("")

    all_alerts = []
    total_pnl = 0
    total_completed = 0

    for strategy_name in ["LockedProductionV1", "NRG3004C1", "TFG3003C1"]:
        strades = get_strategy_trades(trades, strategy_name)
        metrics = compute_metrics(strades)
        exp = EXPECTATIONS.get(strategy_name, {})
        alerts = check_alerts(strategy_name, metrics)
        all_alerts.extend(alerts)

        total_pnl += metrics["total_pnl"]
        total_completed += metrics.get("completed_trades", 0)

        lines.append(f"**{strategy_name}** ({exp.get('style', '?')} — {exp.get('timeframe', '?')})")
        lines.append(f"- Trades: {metrics['completed_trades']} completed ({metrics['entries']} entries, {metrics['exits']} exits)")
        if metrics["completed_trades"] > 0:
            lines.append(f"- Win Rate: {metrics['win_rate']:.0%} (expected: {exp.get('expected_wr', '?'):.0%})")
            lines.append(f"- PnL: ${metrics['total_pnl']:+,.0f} (avg ${metrics['avg_pnl']:+,.0f}/trade)")
            lines.append(f"- Profit Factor: {metrics['profit_factor']}")
            lines.append(f"- Max Win: ${metrics['max_win']:+,.0f} / Max Loss: ${metrics['max_loss']:+,.0f}")
            lines.append(f"- Max Drawdown: ${metrics['max_drawdown']:,.0f}")
            lines.append(f"- Consecutive Losses: {metrics['max_consecutive_losses']} (limit: {ALERTS['max_consecutive_losses']})")
        else:
            lines.append(f"- No completed trades yet")
        lines.append("")

    lines.append(f"**Portfolio Total:** ${total_pnl:+,.0f} across {total_completed} trades")
    lines.append("")

    if all_alerts:
        lines.append("**🚨 Alerts:**")
        for a in all_alerts:
            lines.append(f"- {a}")
    else:
        lines.append("✅ No alerts — all strategies within expected parameters")

    return "\n".join(lines)


def save_report(report: str):
    """Save report to file."""
    REPORT_PATH.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    filename = f"report_{now.strftime('%Y-%m-%d_%H%M')}.md"
    with open(REPORT_PATH / filename, "w") as f:
        f.write(report)


if __name__ == "__main__":
    report = generate_report()
    print(report)
    save_report(report)
