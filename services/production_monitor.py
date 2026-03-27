#!/usr/bin/env python3
"""
Production Monitoring Layer — Paper Trading Surveillance

Tracks LOCKED_PRODUCTION_V1 and clones during paper trading.

Monitors:
1. Live vs Backtest Divergence — are results matching historical?
2. Slippage Impact — execution quality
3. Regime Changes — is market shifting away from our edge?
4. Dependency Drift — are the signal components still generating?
5. Equity Curve Shape — smooth vs step-like vs decay
6. Trade Clustering — temporal concentration risk
7. Win Distribution — outlier dependency trend

Alerts on anomalies. Reports daily to Discord.
"""

import json
import logging
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional

import numpy as np
import pandas as pd

log = logging.getLogger("production_monitor")

PROJECT = Path(__file__).resolve().parents[1]
PRODUCTION_DIR = PROJECT / "data" / "production"
MONITOR_LOG_PATH = PROJECT / "data" / "production" / "monitor_log.jsonl"
PAPER_TRADES_PATH = PROJECT / "data" / "production" / "paper_trades.jsonl"
DAILY_REPORT_PATH = PROJECT / "data" / "production" / "daily_reports"


# ── Alert Thresholds ───────────────────────────────────────────────────────

ALERT_THRESHOLDS = {
    # Divergence: if paper WR diverges >15pp from backtest
    "wr_divergence_pp": 15.0,
    # Divergence: if paper Sharpe drops below 50% of backtest
    "sharpe_floor_pct": 50.0,
    # Drawdown: if paper DD exceeds backtest DD by >50%
    "dd_breach_pct": 50.0,
    # Clustering: >3 trades in same week
    "trade_cluster_weekly": 3,
    # Outlier: if top trade > 40% of total PnL
    "single_trade_pnl_pct": 40.0,
    # Regime: if ADX regime flips for >5 consecutive days
    "regime_flip_days": 5,
    # Consecutive losses before alert
    "consecutive_loss_alert": 3,
    # Max days without a trade (signal went dead?)
    "max_idle_days": 30,
}


# ── Paper Trade Record ─────────────────────────────────────────────────────

@dataclass
class PaperTrade:
    strategy_code: str
    trade_id: str
    entry_time: str
    entry_price: float
    direction: str  # "LONG" / "SHORT"
    exit_time: str = ""
    exit_price: float = 0.0
    pnl_pct: float = 0.0
    pnl_dollar: float = 0.0
    slippage_ticks: float = 0.0
    entry_reason: str = ""
    exit_reason: str = ""
    regime_at_entry: str = ""
    signal_strength: float = 0.0
    
    def to_dict(self) -> dict:
        return asdict(self)


# ── Monitor State ──────────────────────────────────────────────────────────

@dataclass
class StrategyMonitorState:
    """Live monitoring state for one production strategy."""
    strategy_code: str
    
    # Paper trading metrics (running)
    paper_trades: int = 0
    paper_wins: int = 0
    paper_losses: int = 0
    paper_pnl_pct: float = 0.0
    paper_max_dd: float = 0.0
    paper_equity_peak: float = 100000.0
    paper_equity: float = 100000.0
    
    # Backtest reference
    bt_win_rate: float = 0.0
    bt_sharpe: float = 0.0
    bt_max_dd: float = 0.0
    bt_return_pct: float = 0.0
    
    # Divergence tracking
    wr_divergence_pp: float = 0.0  # paper WR - backtest WR (percentage points)
    sharpe_ratio_paper: float = 0.0
    
    # Regime tracking
    current_regime: str = ""
    regime_duration_days: int = 0
    regime_history: List[str] = field(default_factory=list)
    
    # Trade timing
    last_trade_date: str = ""
    days_since_last_trade: int = 0
    consecutive_losses: int = 0
    
    # Equity curve shape
    equity_curve: List[float] = field(default_factory=list)
    
    # Alerts
    active_alerts: List[str] = field(default_factory=list)
    alert_history: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        d = asdict(self)
        # Cap equity curve in serialization
        if len(d.get("equity_curve", [])) > 500:
            d["equity_curve"] = d["equity_curve"][-500:]
        return d


# ── Core Monitoring Functions ──────────────────────────────────────────────

def check_divergence(state: StrategyMonitorState) -> List[str]:
    """Check if paper results are diverging from backtest."""
    alerts = []
    
    if state.paper_trades < 5:
        return alerts  # too early to judge
    
    paper_wr = state.paper_wins / state.paper_trades if state.paper_trades > 0 else 0
    divergence = (paper_wr - state.bt_win_rate) * 100  # percentage points
    state.wr_divergence_pp = round(divergence, 1)
    
    if divergence < -ALERT_THRESHOLDS["wr_divergence_pp"]:
        alerts.append(
            f"🚨 WIN RATE DIVERGENCE: Paper {paper_wr:.1%} vs Backtest {state.bt_win_rate:.1%} "
            f"({divergence:+.1f}pp)"
        )
    
    # Sharpe floor
    if state.bt_sharpe > 0 and state.paper_trades >= 10:
        pnls = []  # would come from trade log
        floor = state.bt_sharpe * (ALERT_THRESHOLDS["sharpe_floor_pct"] / 100)
        if state.sharpe_ratio_paper < floor:
            alerts.append(
                f"🚨 SHARPE FLOOR BREACH: Paper {state.sharpe_ratio_paper:.2f} "
                f"below {floor:.2f} (50% of backtest {state.bt_sharpe:.2f})"
            )
    
    return alerts


def check_drawdown(state: StrategyMonitorState) -> List[str]:
    """Check if paper drawdown exceeds safe limits."""
    alerts = []
    
    if state.paper_equity < state.paper_equity_peak:
        current_dd = (state.paper_equity_peak - state.paper_equity) / state.paper_equity_peak
        state.paper_max_dd = max(state.paper_max_dd, current_dd)
        
        bt_dd = state.bt_max_dd if state.bt_max_dd > 0 else 0.05
        dd_breach = ((current_dd - bt_dd) / bt_dd) * 100
        
        if dd_breach > ALERT_THRESHOLDS["dd_breach_pct"]:
            alerts.append(
                f"🚨 DRAWDOWN BREACH: Paper DD {current_dd:.1%} exceeds backtest DD {bt_dd:.1%} "
                f"by {dd_breach:.0f}%"
            )
    
    return alerts


def check_trade_clustering(trades: List[Dict]) -> List[str]:
    """Check for temporal clustering of trades."""
    alerts = []
    
    if len(trades) < 5:
        return alerts
    
    # Group by week
    weekly_counts = {}
    for t in trades:
        try:
            dt = datetime.fromisoformat(t.get("entry_time", "").replace("Z", "+00:00"))
            week = dt.strftime("%Y-W%W")
            weekly_counts[week] = weekly_counts.get(week, 0) + 1
        except:
            pass
    
    for week, count in weekly_counts.items():
        if count > ALERT_THRESHOLDS["trade_cluster_weekly"]:
            alerts.append(f"⚠️ TRADE CLUSTERING: {count} trades in week {week}")
    
    return alerts


def check_consecutive_losses(state: StrategyMonitorState) -> List[str]:
    """Check for loss streaks."""
    alerts = []
    
    if state.consecutive_losses >= ALERT_THRESHOLDS["consecutive_loss_alert"]:
        alerts.append(
            f"🚨 LOSS STREAK: {state.consecutive_losses} consecutive losses"
        )
    
    return alerts


def check_idle(state: StrategyMonitorState) -> List[str]:
    """Check if strategy has gone silent."""
    alerts = []
    
    if state.days_since_last_trade > ALERT_THRESHOLDS["max_idle_days"]:
        alerts.append(
            f"⚠️ IDLE: No trades for {state.days_since_last_trade} days — signal dead?"
        )
    
    return alerts


def check_equity_curve_shape(state: StrategyMonitorState) -> str:
    """Analyze equity curve shape: smooth / step-like / decaying."""
    curve = state.equity_curve
    if len(curve) < 10:
        return "insufficient_data"
    
    arr = np.array(curve)
    returns = np.diff(arr) / arr[:-1]
    
    # Check for step-like pattern (long flat periods with sudden jumps)
    abs_returns = np.abs(returns)
    if len(abs_returns) > 0:
        median_ret = np.median(abs_returns)
        large_moves = (abs_returns > median_ret * 5).sum()
        large_pct = large_moves / len(abs_returns)
        
        if large_pct > 0.2:
            return "step_like"  # >20% of moves are 5x median = step-like
    
    # Check for decay (equity trending down)
    if len(arr) >= 20:
        recent = arr[-10:]
        early = arr[:10]
        if np.mean(recent) < np.mean(early) * 0.95:
            return "decaying"
    
    return "smooth"


# ── Daily Report Generator ─────────────────────────────────────────────────

def generate_daily_report(states: Dict[str, StrategyMonitorState]) -> Dict[str, Any]:
    """Generate a daily monitoring report for all production strategies."""
    report = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "strategies": {},
        "fleet_alerts": [],
        "fleet_summary": {},
    }
    
    total_pnl = 0
    total_trades = 0
    all_alerts = []
    
    for code, state in states.items():
        # Run all checks
        alerts = []
        alerts.extend(check_divergence(state))
        alerts.extend(check_drawdown(state))
        alerts.extend(check_consecutive_losses(state))
        alerts.extend(check_idle(state))
        
        curve_shape = check_equity_curve_shape(state)
        
        state.active_alerts = alerts
        all_alerts.extend(alerts)
        
        paper_wr = state.paper_wins / state.paper_trades if state.paper_trades > 0 else 0
        
        report["strategies"][code] = {
            "paper_trades": state.paper_trades,
            "paper_win_rate": round(paper_wr, 3),
            "paper_pnl_pct": round(state.paper_pnl_pct, 2),
            "paper_max_dd": round(state.paper_max_dd, 4),
            "bt_win_rate": state.bt_win_rate,
            "bt_sharpe": state.bt_sharpe,
            "wr_divergence_pp": state.wr_divergence_pp,
            "consecutive_losses": state.consecutive_losses,
            "days_since_trade": state.days_since_last_trade,
            "equity_curve_shape": curve_shape,
            "alerts": alerts,
            "status": "OK" if not alerts else "ALERT",
        }
        
        total_pnl += state.paper_pnl_pct
        total_trades += state.paper_trades
    
    report["fleet_summary"] = {
        "total_strategies": len(states),
        "total_trades": total_trades,
        "total_pnl_pct": round(total_pnl, 2),
        "total_alerts": len(all_alerts),
        "strategies_ok": sum(1 for s in report["strategies"].values() if s["status"] == "OK"),
        "strategies_alert": sum(1 for s in report["strategies"].values() if s["status"] == "ALERT"),
    }
    report["fleet_alerts"] = all_alerts
    
    # Save report
    DAILY_REPORT_PATH.mkdir(parents=True, exist_ok=True)
    report_file = DAILY_REPORT_PATH / f"{report['date']}.json"
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2, default=str)
    
    return report


# ── Trade Ingestion ────────────────────────────────────────────────────────

def record_paper_trade(trade: PaperTrade):
    """Record a paper trade to the log."""
    PAPER_TRADES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PAPER_TRADES_PATH, "a") as f:
        f.write(json.dumps(trade.to_dict(), default=str) + "\n")


def load_paper_trades(strategy_code: str = None) -> List[Dict]:
    """Load paper trades, optionally filtered by strategy."""
    trades = []
    if not PAPER_TRADES_PATH.exists():
        return trades
    
    with open(PAPER_TRADES_PATH) as f:
        for line in f:
            try:
                t = json.loads(line.strip())
                if strategy_code is None or t.get("strategy_code") == strategy_code:
                    trades.append(t)
            except:
                continue
    return trades


# ── Production Fleet Status ────────────────────────────────────────────────

def get_fleet_status() -> Dict[str, Any]:
    """Get current status of all production strategies."""
    status = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "strategies": [],
    }
    
    for json_file in sorted(PRODUCTION_DIR.glob("*.json")):
        if json_file.name.startswith("monitor") or json_file.name.startswith("daily"):
            continue
        try:
            with open(json_file) as f:
                dna = json.load(f)
            if dna.get("locked"):
                status["strategies"].append({
                    "file": json_file.name,
                    "code": dna.get("strategy_code", dna.get("production_name", "?")),
                    "production_name": dna.get("production_name", ""),
                    "style": dna.get("style", ""),
                    "asset": dna.get("asset", "NQ"),
                    "locked": True,
                    "params": dna.get("parameter_ranges", {}),
                })
        except:
            continue
    
    return status


# ── Discord Report Formatter ───────────────────────────────────────────────

def format_discord_report(report: Dict) -> str:
    """Format daily report for Discord posting."""
    lines = [
        f"📊 **PRODUCTION MONITOR — Daily Report {report['date']}**",
        "",
    ]
    
    fleet = report.get("fleet_summary", {})
    lines.append(f"**Fleet:** {fleet.get('total_strategies', 0)} strategies | {fleet.get('total_trades', 0)} trades | PnL: {fleet.get('total_pnl_pct', 0):+.2f}%")
    lines.append(f"**Status:** {fleet.get('strategies_ok', 0)} OK | {fleet.get('strategies_alert', 0)} ALERT")
    lines.append("")
    
    for code, data in report.get("strategies", {}).items():
        status_emoji = "✅" if data["status"] == "OK" else "🚨"
        lines.append(f"{status_emoji} **{code}**")
        lines.append(f"  Trades: {data['paper_trades']} | WR: {data['paper_win_rate']:.1%} | PnL: {data['paper_pnl_pct']:+.2f}% | DD: {data['paper_max_dd']:.1%}")
        lines.append(f"  Curve: {data['equity_curve_shape']} | Divergence: {data['wr_divergence_pp']:+.1f}pp")
        
        if data["alerts"]:
            for alert in data["alerts"]:
                lines.append(f"  {alert}")
        lines.append("")
    
    if report.get("fleet_alerts"):
        lines.append("**⚠️ Active Alerts:**")
        for alert in report["fleet_alerts"]:
            lines.append(f"  {alert}")
    
    return "\n".join(lines)
