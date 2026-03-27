#!/usr/bin/env python3
"""
Central Alert Function — Unified severity-based routing.
One alert system, three channels, zero ambiguity.

Severity levels:
  🔴 CRITICAL → #alerts-critical + #ceo-feed
  🟡 HIGH     → #system-alerts + #ceo-feed
  🔵 MEDIUM   → #system-alerts
  ⚪ LOW      → #system-alerts

Channels:
  #ceo-feed         — business-critical only
  #alerts-critical  — must-act signals
  #system-alerts    — main event stream

Usage:
    from services.central_alerts import alert
    alert("CRITICAL", "🔴 PROP FAILED", "DD breach at 10.2%", context={...})
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("central_alerts")

BASE = Path(__file__).resolve().parents[1]
DATA = BASE / "data"

# Channel IDs
CHANNELS = {
    "ceo_feed": os.getenv("DISCORD_CEO_CHANNEL", ""),
    "alerts_critical": os.getenv("DISCORD_ALERTS_CHANNEL", ""),
    "system_alerts": os.getenv("DISCORD_SYSTEM_CHANNEL", ""),
}

# Routing rules
ROUTING = {
    "CRITICAL": ["alerts_critical", "ceo_feed"],
    "HIGH": ["system_alerts", "ceo_feed"],
    "MEDIUM": ["system_alerts"],
    "LOW": ["system_alerts"],
}

SEVERITY_EMOJI = {
    "CRITICAL": "🔴",
    "HIGH": "🟡",
    "MEDIUM": "🔵",
    "LOW": "⚪",
}

# State files
ALERT_STATE_FILE = DATA / "alert_state.json"
ALERT_QUEUE_FILE = DATA / "alert_queue.jsonl"
MILESTONE_LOG_FILE = DATA / "milestone_log.jsonl"


# =============================================================================
# CORE ALERT FUNCTION
# =============================================================================

def alert(severity: str, title: str, body: str = "", context: dict = None):
    """
    Send alert with severity-based routing.
    
    severity: CRITICAL, HIGH, MEDIUM, LOW
    title: short headline (e.g., "🔴 PROP FAILED")
    body: details
    context: optional system snapshot dict
    """
    severity = severity.upper()
    if severity not in ROUTING:
        severity = "LOW"

    emoji = SEVERITY_EMOJI.get(severity, "⚪")
    
    # Build message
    msg_parts = [f"**[{severity}]** {title}"]
    if body:
        msg_parts.append(body)
    if context:
        ctx_str = _format_context(context)
        if ctx_str:
            msg_parts.append(f"**Context:** {ctx_str}")

    message = "\n".join(msg_parts)

    # Route to channels
    targets = ROUTING[severity]
    for target in targets:
        channel_id = CHANNELS.get(target)
        if channel_id:
            _queue_alert(channel_id, message, severity)

    log.info(f"Alert [{severity}] → {targets}: {title}")


def _queue_alert(channel_id: str, message: str, severity: str):
    """Queue alert for processing by cron."""
    entry = {
        "channel_id": channel_id,
        "message": message,
        "severity": severity,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sent": False,
    }
    ALERT_QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(ALERT_QUEUE_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


# =============================================================================
# CONTEXT SNAPSHOT
# =============================================================================

def get_system_context() -> dict:
    """Get current system state for alert context."""
    ctx = {}
    try:
        bt = _read_json(DATA / "backtester_v2_state.json", {})
        ctx["gen"] = bt.get("generation", 0)
        ctx["tested"] = bt.get("total_strategies_tested", 0)
        ctx["passed"] = bt.get("total_passed", 0)

        disc = _read_last_jsonl(DATA / "discovery_rate.jsonl", 1)
        if disc:
            ctx["discovery_rate"] = disc[0].get("rate", 0)
            ctx["fitness_mean"] = disc[0].get("mean_fitness", 0)
            ctx["bias_influence"] = disc[0].get("bias_influence", 0)

        ctrl = _read_json(DATA / "control_state.json", {})
        ctx["control"] = ctrl.get("last_action", "?")

        nm = DATA / "near_misses.jsonl"
        if nm.exists():
            with open(nm) as f:
                ctx["near_misses"] = sum(1 for _ in f)
    except Exception:
        pass
    return ctx


def _format_context(ctx: dict) -> str:
    parts = []
    if ctx.get("gen"): parts.append(f"Gen {ctx['gen']}")
    if ctx.get("discovery_rate"): parts.append(f"Discovery {ctx['discovery_rate']:.3%}")
    if ctx.get("bias_influence"): parts.append(f"Bias {ctx['bias_influence']:.0%}")
    if ctx.get("fitness_mean"): parts.append(f"Fitness {ctx['fitness_mean']:.3f}")
    if ctx.get("control"): parts.append(f"Control: {ctx['control']}")
    return " | ".join(parts)


def _read_json(path, default=None):
    if not path.exists(): return default
    try:
        with open(path) as f: return json.load(f)
    except: return default


def _read_last_jsonl(path, n=1):
    if not path.exists(): return []
    lines = []
    with open(path) as f:
        for line in f: lines.append(line.strip())
    result = []
    for l in lines[-n:]:
        try: result.append(json.loads(l))
        except: pass
    return result


def _append_milestone(entry: dict):
    MILESTONE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MILESTONE_LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


# =============================================================================
# MILESTONE STATE
# =============================================================================

def _load_state() -> dict:
    if ALERT_STATE_FILE.exists():
        try:
            with open(ALERT_STATE_FILE) as f: return json.load(f)
        except: pass
    return {
        "milestones": {
            "first_v2_darwin_production": False,
            "first_v2_darwin_exploration": False,
            "first_live_trade": False,
            "first_promotion": False,
        },
        "alerts_sent": 0,
    }


def _save_state(state: dict):
    ALERT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(ALERT_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# =============================================================================
# SPECIFIC ALERT FUNCTIONS (called by other services)
# =============================================================================

def alert_darwin_pass(strategy_code: str, tier: str, metrics: dict):
    """Darwin pass — production or exploration."""
    state = _load_state()
    ctx = get_system_context()

    if tier == "production" and not state["milestones"].get("first_v2_darwin_production"):
        alert("HIGH",
            f"🏆 FIRST V2 DARWIN PRODUCTION PASS!",
            f"**Strategy:** `{strategy_code}` ({metrics.get('style', '?')})\n"
            f"Trades: {metrics.get('trade_count', 0)} | WR: {metrics.get('win_rate', 0):.0%} | "
            f"Sharpe: {metrics.get('sharpe_ratio', 0):.2f} | DD: {metrics.get('max_drawdown', 0):.1%} | "
            f"PF: {metrics.get('profit_factor', 0):.1f} | Fitness: {metrics.get('fitness', 0):.3f}\n"
            f"Passed ALL production gates. Eligible for capital.",
            ctx)
        _append_milestone({"event": "FIRST_V2_PRODUCTION", "strategy": strategy_code, "metrics": metrics, "context": ctx, "ts": datetime.now(timezone.utc).isoformat()})
        state["milestones"]["first_v2_darwin_production"] = True
        state["alerts_sent"] += 1
        _save_state(state)

    elif tier == "exploration" and not state["milestones"].get("first_v2_darwin_exploration"):
        alert("MEDIUM",
            f"🟡 First V2 Darwin Exploration Pass",
            f"**Strategy:** `{strategy_code}` ({metrics.get('style', '?')})\n"
            f"Trades: {metrics.get('trade_count', 0)} | Sharpe: {metrics.get('sharpe_ratio', 0):.2f}\n"
            f"Not tradable yet — system is finding signal.",
            ctx)
        _append_milestone({"event": "FIRST_V2_EXPLORATION", "strategy": strategy_code, "context": ctx, "ts": datetime.now(timezone.utc).isoformat()})
        state["milestones"]["first_v2_darwin_exploration"] = True
        state["alerts_sent"] += 1
        _save_state(state)


def alert_live_trade(strategy: str, direction: str, price: float, action: str):
    """First live trade from NinjaTrader."""
    state = _load_state()
    if not state["milestones"].get("first_live_trade"):
        ctx = get_system_context()
        alert("HIGH",
            f"📊 FIRST LIVE TRADE! Full loop complete.",
            f"**Strategy:** `{strategy}`\n"
            f"Action: {action.upper()} {direction} @ {price:.2f}\n"
            f"Source: NinjaTrader webhook",
            ctx)
        _append_milestone({"event": "FIRST_LIVE_TRADE", "strategy": strategy, "price": price, "context": ctx, "ts": datetime.now(timezone.utc).isoformat()})
        state["milestones"]["first_live_trade"] = True
        state["alerts_sent"] += 1
        _save_state(state)


def alert_promotion(strategy_code: str, metrics: dict):
    """Exploration → production promotion."""
    state = _load_state()
    if not state["milestones"].get("first_promotion"):
        ctx = get_system_context()
        alert("HIGH",
            f"🎯 First Strategy Promotion! Exploration → Production",
            f"**Strategy:** `{strategy_code}`\nPassed all promotion gates.",
            ctx)
        state["milestones"]["first_promotion"] = True
        state["alerts_sent"] += 1
        _save_state(state)


# Safety alerts (fire every time)

def alert_kill(strategy: str, reason: str):
    alert("MEDIUM", f"🛑 Strategy KILLED: `{strategy}`", f"Reason: {reason}\n24h cooldown.")

def alert_recovery(strategy: str):
    alert("LOW", f"🔄 Strategy Recovering: `{strategy}`", "Cooldown expired, metrics improved. Re-entering at 30%.")

def alert_portfolio_dd(dd_pct: float, scale: float):
    severity = "CRITICAL" if scale == 0 else "HIGH"
    alert(severity, f"{'⛔ TRADING HALTED' if scale == 0 else '⚠️ Portfolio DD Breach'}", f"DD: {dd_pct:.1%} | Scale: {scale:.0%}")

# Prop alerts (routed by severity, not channel)

def alert_prop_zone(from_zone: str, to_zone: str, dd: float, pressure: float, balance: float):
    """Prop risk zone transition."""
    zone_severity = {"CAUTION": "MEDIUM", "DANGER": "HIGH", "CRITICAL": "CRITICAL"}
    if to_zone in ("SAFE",):
        # Recovery
        alert("LOW", f"🔄 Prop Recovery: {from_zone} → {to_zone}", f"DD: {dd:.1f}% | Pressure: {pressure:.1f}x | Balance: ${balance:,.0f}")
    else:
        sev = zone_severity.get(to_zone, "MEDIUM")
        alert(sev, f"🏦 Prop Zone: {from_zone} → {to_zone}", f"DD: {dd:.1f}% | Pressure: {pressure:.1f}x | Balance: ${balance:,.0f}")

def alert_prop_near_fail(dd: float, balance: float):
    alert("CRITICAL", f"🧨 PROP NEAR-FAIL WARNING", f"DD: {dd:.1f}% — approaching limit\nBalance: ${balance:,.0f}")

def alert_prop_phase(event: str, details: str):
    """Phase transition — pass/fail/funded."""
    severity = "CRITICAL" if "FAIL" in event.upper() else "HIGH"
    alert(severity, f"🏦 {event}", details)

def alert_health_warning(warnings: list):
    if warnings:
        alert("MEDIUM", "⚠️ System Health Warnings", "\n".join(f"  {w}" for w in warnings))


# =============================================================================
# STANDALONE CHECK
# =============================================================================

def check_milestones():
    """Scan for milestone events."""
    state = _load_state()
    
    if not state["milestones"].get("first_v2_darwin_production") or not state["milestones"].get("first_v2_darwin_exploration"):
        try:
            with open(DATA / "continuous_run_log.jsonl") as f:
                for line in f:
                    try:
                        d = json.loads(line.strip())
                        tier = d.get("darwin_tier", "")
                        if tier in ("production", "exploration"):
                            alert_darwin_pass(d.get("strategy_code", "?"), tier, d)
                    except: pass
        except: pass

    if not state["milestones"].get("first_live_trade"):
        try:
            trades = json.load(open(DATA / "paper_trading" / "trades.json"))
            if isinstance(trades, list) and trades:
                t = trades[-1]
                alert_live_trade(t.get("system", "?"), t.get("direction", "?"), t.get("entry_price", 0), t.get("action", "?"))
        except: pass

    state["last_check"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if "--check" in sys.argv:
        check_milestones()
    else:
        state = _load_state()
        print(f"Milestones: {json.dumps(state.get('milestones', {}), indent=2)}")
        print(f"Alerts sent: {state.get('alerts_sent', 0)}")
