import os
"""
Discord Paper Trading Monitor
===============================
Real-time trade alerts, performance tracking, and risk notifications
delivered to Discord via OpenClaw's message tool.

Events:
  1. Trade Open — entry signal with context
  2. Trade Close — PnL + updated stats + weight change
  3. Daily Summary — aggregate performance
  4. Risk Alerts — DD breach, sharpe collapse, weight reduction

Channel: #paper-trading-live

This module is called by the paper signal engine and webhook receiver.
It formats and queues Discord messages via the alert system.

Author: Henry (autonomous build)
Date: 2026-03-26
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("discord_paper_monitor")

BASE_DIR = Path("Path(__file__).resolve().parents[1]")
ALERT_QUEUE = BASE_DIR / "data" / "alert_queue.jsonl"

# Discord channel
PAPER_CHANNEL = os.getenv("DISCORD_PAPER_CHANNEL", "")

# Alert thresholds
DD_ALERT_MULTIPLIER = 1.2   # Alert when live DD > 1.2x MC expected
SHARPE_DRIFT_THRESHOLD = 0.5  # Alert when live sharpe drops >0.5 below backtest
MAX_LOSS_ALERT_PCT = 0.03    # Alert on single trade loss > 3%


def _queue_discord(message: str, severity: str = "info"):
    """Queue a message for Discord delivery via the alert system."""
    ALERT_QUEUE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "channel_id": PAPER_CHANNEL,
        "message": message,
        "severity": severity,
        "sent": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "paper_monitor",
    }
    with open(ALERT_QUEUE, "a") as f:
        f.write(json.dumps(entry, separators=(",", ":"), default=str) + "\n")


# ─── Event Formatters ─────────────────────────────────────────────────

def on_trade_open(
    strategy_code: str,
    direction: str,
    price: float,
    asset: str,
    style: str,
    weight: float,
    live_sharpe: float = 0,
    live_dd: float = 0,
    live_trades: int = 0,
):
    """Format and queue trade open alert."""
    msg = (
        f"🟢 **TRADE OPEN** — {strategy_code}\n"
        f"Direction: {direction}\n"
        f"Price: {price}\n"
        f"Asset: {asset} | Style: {style}\n"
        f"Size: 1 contract\n"
        f"Weight: {weight:.0%}\n"
        f"Time: {datetime.now(timezone.utc).strftime('%H:%M UTC')}\n"
    )
    if live_trades > 0:
        msg += (
            f"\nContext:\n"
            f"Sharpe (live): {live_sharpe:.2f}\n"
            f"DD: {live_dd:.2%}\n"
            f"Trades: {live_trades}"
        )
    
    _queue_discord(msg, "info")
    log.info(f"Discord: trade open queued for {strategy_code}")


def on_trade_close(
    strategy_code: str,
    direction: str,
    entry_price: float,
    exit_price: float,
    pnl_pct: float,
    pnl_dollars: float,
    duration_mins: int,
    # Updated stats
    total_trades: int,
    win_rate: float,
    live_sharpe: float,
    rolling_sharpe: float,
    # PnL profile
    avg_win: float,
    avg_loss: float,
    max_loss: float,
    wl_ratio: float,
    # Weight
    old_weight: float,
    new_weight: float,
    # Backtest reference
    bt_sharpe: float = 0,
    mc_worst_dd: float = 0,
    live_dd: float = 0,
):
    """Format and queue trade close alert."""
    pnl_icon = "💰" if pnl_pct > 0 else "🔻"
    weight_arrow = "↑" if new_weight > old_weight else "↓" if new_weight < old_weight else "→"
    
    msg = (
        f"🔵 **TRADE CLOSED** — {strategy_code}\n"
        f"{pnl_icon} PnL: ${pnl_dollars:+.0f} ({pnl_pct:+.2%})\n"
        f"Duration: {duration_mins} min\n"
        f"Entry: {entry_price} → Exit: {exit_price}\n"
        f"\n📊 Updated Stats:\n"
        f"Trades: {total_trades}\n"
        f"Win Rate: {win_rate:.1%}\n"
        f"Sharpe (live): {live_sharpe:.2f} (backtest: {bt_sharpe:.2f})\n"
        f"Rolling Sharpe (20): {rolling_sharpe:.2f}\n"
        f"\n💰 PnL Profile:\n"
        f"Avg Win: ${avg_win * 100:+.0f}\n"
        f"Avg Loss: ${avg_loss * 100:+.0f}\n"
        f"Max Loss: ${max_loss * 100:+.0f}\n"
        f"W/L Ratio: {wl_ratio:.2f}x\n"
        f"\n⚖️ Weight: {new_weight:.0%} {weight_arrow}"
    )
    
    _queue_discord(msg, "info")
    
    # Check for risk alerts on close
    _check_risk_alerts(
        strategy_code, live_sharpe, bt_sharpe,
        live_dd, mc_worst_dd, pnl_pct, max_loss,
    )
    
    log.info(f"Discord: trade close queued for {strategy_code} (pnl={pnl_pct:+.2%})")


def on_daily_summary(
    total_pnl: float,
    total_trades: int,
    strategy_results: list,  # [{code, pnl, trades}]
    weights: dict,           # {code: weight}
):
    """Format and queue daily summary."""
    sorted_strats = sorted(strategy_results, key=lambda x: x.get("pnl", 0), reverse=True)
    
    msg = (
        f"📅 **DAILY SUMMARY**\n"
        f"\nTotal PnL: ${total_pnl * 100:+.0f}\n"
        f"Trades: {total_trades}\n"
    )
    
    if sorted_strats:
        best = sorted_strats[0]
        worst = sorted_strats[-1]
        msg += (
            f"\nTop Strategy:\n"
            f"{best['code']} (${best['pnl'] * 100:+.0f})\n"
            f"\nWorst Strategy:\n"
            f"{worst['code']} (${worst['pnl'] * 100:+.0f})\n"
        )
    
    msg += "\n⚖️ Current Weights:"
    for code, weight in sorted(weights.items(), key=lambda x: -x[1]):
        msg += f"\n{code} — {weight:.0%}"
    
    _queue_discord(msg, "info")
    log.info("Discord: daily summary queued")


# ─── Risk Alerts ──────────────────────────────────────────────────────

def _check_risk_alerts(
    strategy_code: str,
    live_sharpe: float,
    bt_sharpe: float,
    live_dd: float,
    mc_worst_dd: float,
    last_pnl: float,
    max_loss: float,
):
    """Check for risk conditions and emit alerts."""
    
    # DD breach
    if mc_worst_dd > 0 and live_dd > mc_worst_dd * DD_ALERT_MULTIPLIER:
        msg = (
            f"🚨 **ALERT — DD EXCEEDED**\n"
            f"Strategy: {strategy_code}\n"
            f"Live DD: {live_dd:.2%}\n"
            f"MC Expected Max: {mc_worst_dd:.2%}\n"
            f"\nAction: Review for weight reduction"
        )
        _queue_discord(msg, "critical")
        log.warning(f"RISK ALERT: DD breach for {strategy_code}")
    
    # Sharpe collapse
    if bt_sharpe > 0 and (bt_sharpe - live_sharpe) > SHARPE_DRIFT_THRESHOLD:
        msg = (
            f"⚠️ **ALERT — SHARPE DRIFT**\n"
            f"Strategy: {strategy_code}\n"
            f"\nBacktest: {bt_sharpe:.2f}\n"
            f"Live: {live_sharpe:.2f}\n"
            f"Drift: {bt_sharpe - live_sharpe:+.2f}\n"
            f"\nPossible degradation detected"
        )
        _queue_discord(msg, "warning")
        log.warning(f"RISK ALERT: sharpe drift for {strategy_code}")
    
    # Large single loss
    if last_pnl < -MAX_LOSS_ALERT_PCT:
        msg = (
            f"⚠️ **ALERT — LARGE LOSS**\n"
            f"Strategy: {strategy_code}\n"
            f"Trade PnL: {last_pnl:+.2%}\n"
            f"Max Loss (history): {max_loss:+.2%}\n"
            f"\nMonitoring tail risk"
        )
        _queue_discord(msg, "warning")
        log.warning(f"RISK ALERT: large loss for {strategy_code}")


def alert_paper_gate_approved(strategy_code: str, fitness: float, sharpe: float, trades: int):
    """Alert when a new strategy passes paper gate."""
    msg = (
        f"📄 **NEW PAPER STRATEGY APPROVED**\n"
        f"Strategy: {strategy_code}\n"
        f"Fitness: {fitness:.3f}\n"
        f"Sharpe: {sharpe:.2f}\n"
        f"Backtest Trades: {trades}\n"
        f"\nAdded to paper trading pool"
    )
    _queue_discord(msg, "info")


def alert_promotion_eligible(strategy_code: str, live_sharpe: float, live_trades: int, live_wr: float):
    """Alert when a strategy hits promotion criteria."""
    msg = (
        f"🏆 **PROMOTION ELIGIBLE**\n"
        f"Strategy: {strategy_code}\n"
        f"\nLive Sharpe: {live_sharpe:.2f}\n"
        f"Live Trades: {live_trades}\n"
        f"Live Win Rate: {live_wr:.1%}\n"
        f"\nReady for Production Gate review"
    )
    _queue_discord(msg, "critical")


if __name__ == "__main__":
    # Test: queue a test alert
    print("Queueing test alerts...")
    on_trade_open(
        "TEST-001", "LONG", 20150.25, "NQ", "mean_reversion",
        weight=0.25, live_sharpe=0, live_dd=0, live_trades=0,
    )
    print(f"Alert queued to {ALERT_QUEUE}")
    print("Run the alert queue processor to send to Discord.")
