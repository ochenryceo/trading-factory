#!/usr/bin/env python3
"""
Prop Challenge Tracker — Stage 1: Soft Pressure Mode
=====================================================
Tracks a virtual prop account from paper trades. Applies progressive pressure
to the risk system — NOT hard stops. The system learns to survive constraints.

Prop phases (FTMO-style):
  Phase 1: Challenge — 10% profit target, 5% daily DD limit, 10% total DD limit, 30 days
  Phase 2: Verification — 5% profit target, 5% daily DD, 10% total DD, 60 days
  Funded: Live — no profit target, 5% daily DD, 10% total DD

Usage:
    python prop_tracker.py              # show current status
    python prop_tracker.py --daemon     # check every 5 minutes
    python prop_tracker.py --reset      # reset account (new challenge)

Integration:
    Drift monitor reads prop_status.json for prop_pressure multiplier.
"""

import argparse
import json
import logging
import signal
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

log = logging.getLogger("prop_tracker")

BASE = Path(__file__).resolve().parents[1]
DATA = BASE / "data"
TRADES_FILE = DATA / "paper_trading" / "trades.json"
PROP_STATUS_FILE = DATA / "prop_status.json"
PROP_HISTORY_FILE = DATA / "prop_history.jsonl"

# Risk zones — alert ONLY on transitions between these
RISK_ZONES = [
    ("SAFE", 0, 2.0),
    ("CAUTION", 2.0, 4.0),
    ("DANGER", 4.0, 5.0),
    ("CRITICAL", 5.0, 100.0),
]

ZONE_EMOJI = {
    "SAFE": "🟢",
    "CAUTION": "🟡",
    "DANGER": "🟠",
    "CRITICAL": "🔴",
}

# =============================================================================
# PROP CHALLENGE CONFIG
# =============================================================================

STARTING_BALANCE = 50_000  # Virtual starting balance

PHASES = {
    "phase_1": {
        "name": "Challenge",
        "profit_target_pct": 10.0,
        "max_daily_dd_pct": 5.0,
        "max_total_dd_pct": 10.0,
        "time_limit_days": 30,
    },
    "phase_2": {
        "name": "Verification",
        "profit_target_pct": 5.0,
        "max_daily_dd_pct": 5.0,
        "max_total_dd_pct": 10.0,
        "time_limit_days": 60,
    },
    "funded": {
        "name": "Funded",
        "profit_target_pct": None,  # No target — just survive
        "max_daily_dd_pct": 5.0,
        "max_total_dd_pct": 10.0,
        "time_limit_days": None,
    },
}


# =============================================================================
# PROP ACCOUNT
# =============================================================================

def _default_account() -> dict:
    return {
        "balance": STARTING_BALANCE,
        "peak": STARTING_BALANCE,
        "starting_balance": STARTING_BALANCE,
        "phase": "phase_1",
        "status": "active",  # active, passed, failed
        "start_date": datetime.now(timezone.utc).isoformat(),
        "trades_processed": 0,
        "daily_pnl": {},  # {"2026-03-25": -500, ...}
        "total_pnl": 0.0,
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
    }


def load_account() -> dict:
    if PROP_STATUS_FILE.exists():
        try:
            with open(PROP_STATUS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    acc = _default_account()
    save_account(acc)
    return acc


def save_account(acc: dict):
    PROP_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PROP_STATUS_FILE, "w") as f:
        json.dump(acc, f, indent=2)


def reset_account():
    acc = _default_account()
    save_account(acc)
    log.info("Prop account reset to Phase 1")
    return acc


# =============================================================================
# TRADE PROCESSING
# =============================================================================

def process_trades(acc: dict) -> dict:
    """Process new trades from webhook and update account."""
    trades = []
    if TRADES_FILE.exists():
        try:
            with open(TRADES_FILE) as f:
                data = json.load(f)
                trades = data if isinstance(data, list) else []
        except Exception:
            return acc

    # Only process new trades
    already = acc.get("trades_processed", 0)
    new_trades = [t for t in trades if t.get("action") == "exit" and t.get("pnl_dollars", 0) != 0]

    if len(new_trades) <= already:
        return acc  # nothing new

    for t in new_trades[already:]:
        pnl = float(t.get("pnl_dollars", 0))
        ts = t.get("timestamp", "")
        day = ts[:10] if len(ts) >= 10 else datetime.now(timezone.utc).strftime("%Y-%m-%d")

        acc["balance"] += pnl
        acc["total_pnl"] += pnl
        acc["total_trades"] += 1
        if pnl > 0:
            acc["wins"] += 1
        elif pnl < 0:
            acc["losses"] += 1

        # Track peak
        if acc["balance"] > acc["peak"]:
            acc["peak"] = acc["balance"]

        # Daily PnL
        acc["daily_pnl"][day] = acc["daily_pnl"].get(day, 0) + pnl

        acc["trades_processed"] = acc.get("trades_processed", 0) + 1

    save_account(acc)
    return acc


# =============================================================================
# PROP HEALTH + PRESSURE
# =============================================================================

def get_prop_health(acc: dict) -> float:
    """Account health: 1.0 = perfect, <1 = in drawdown."""
    if acc["peak"] <= 0:
        return 1.0
    return acc["balance"] / acc["peak"]


def get_daily_dd(acc: dict) -> float:
    """Today's drawdown as percentage of starting balance."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily_pnl = acc.get("daily_pnl", {}).get(today, 0)
    return daily_pnl / acc["starting_balance"] * 100  # negative = drawdown


def get_total_dd(acc: dict) -> float:
    """Total drawdown from peak as percentage."""
    if acc["peak"] <= 0:
        return 0.0
    return (acc["peak"] - acc["balance"]) / acc["peak"] * 100


MIN_PROP_SCALE = 0.15  # hard floor — never fully starve capital

def prop_pressure(acc: dict) -> float:
    """
    Soft pressure curve — progressive weight scaling based on prop DD.
    With hard floor (0.15) and recovery boost.
    
      DD < 2% → 1.0 (no pressure)
      DD 2-4% → 0.7
      DD 4-5% → 0.4
      DD > 5% → 0.2 (floor: 0.15)
    
    Recovery boost: if health > 98% and coming back from DD → 1.1x
    """
    total_dd_pct = get_total_dd(acc)
    health = get_prop_health(acc)

    if total_dd_pct < 2.0:
        scale = 1.0
    elif total_dd_pct < 4.0:
        scale = 0.7
    elif total_dd_pct < 5.0:
        scale = 0.4
    else:
        scale = 0.2

    # Recovery boost — encourage controlled recovery
    # If health is near peak AND we were previously in drawdown
    peak_dd_ever = (acc.get("peak", acc["starting_balance"]) - acc.get("starting_balance", 50000)) > 0
    if health > 0.98 and peak_dd_ever and total_dd_pct < 1.0:
        scale = min(1.1, scale * 1.1)  # 10% boost, capped at 1.1

    return max(MIN_PROP_SCALE, scale)


def check_phase_status(acc: dict) -> dict:
    """Check if phase passed or failed."""
    phase = acc.get("phase", "phase_1")
    phase_config = PHASES.get(phase, PHASES["phase_1"])
    status = acc.get("status", "active")

    if status != "active":
        return acc

    total_dd = get_total_dd(acc)
    daily_dd = abs(get_daily_dd(acc))
    profit_pct = (acc["balance"] - acc["starting_balance"]) / acc["starting_balance"] * 100

    # Check failure conditions
    if total_dd >= phase_config["max_total_dd_pct"]:
        acc["status"] = "failed"
        acc["fail_reason"] = f"Total DD {total_dd:.1f}% >= {phase_config['max_total_dd_pct']}%"
        log.error(f"🔴 PROP FAILED: {acc['fail_reason']}")
        _log_history(acc, "FAILED")
        _queue_prop_alert(f"🔴 **PROP FAILED** — {acc['fail_reason']}\nBalance: ${acc['balance']:,.0f} | {acc['total_trades']} trades", severity="CRITICAL")
        try:
            from services.central_alerts import _send_discord
            _send_discord(f"🔴 **PROP CHALLENGE FAILED** — {acc['fail_reason']}\nBalance: ${acc['balance']:,.0f} (started ${acc['starting_balance']:,.0f})")
        except Exception:
            pass
        return acc

    if daily_dd >= phase_config["max_daily_dd_pct"]:
        acc["status"] = "failed"
        acc["fail_reason"] = f"Daily DD {daily_dd:.1f}% >= {phase_config['max_daily_dd_pct']}%"
        log.error(f"🔴 PROP FAILED: {acc['fail_reason']}")
        _log_history(acc, "FAILED")
        return acc

    # Check time limit
    if phase_config.get("time_limit_days"):
        start = datetime.fromisoformat(acc["start_date"])
        elapsed = (datetime.now(timezone.utc) - start).days
        if elapsed > phase_config["time_limit_days"]:
            if profit_pct < (phase_config.get("profit_target_pct") or 0):
                acc["status"] = "failed"
                acc["fail_reason"] = f"Time expired ({elapsed}d) without reaching {phase_config['profit_target_pct']}% target"
                _log_history(acc, "FAILED")
                return acc

    # Check profit target (phase pass)
    target = phase_config.get("profit_target_pct")
    if target and profit_pct >= target:
        acc["status"] = "passed"
        log.info(f"🟢 PROP PHASE PASSED: {phase} — profit {profit_pct:.1f}% >= {target}%")
        _log_history(acc, "PASSED")
        try:
            from services.central_alerts import _send_discord
            _send_discord(f"🟢 **PROP {phase_config['name'].upper()} PASSED!** — Profit: {profit_pct:.1f}%\nBalance: ${acc['balance']:,.0f}")
        except Exception:
            pass

        # Auto-advance to next phase
        if phase == "phase_1":
            acc["phase"] = "phase_2"
            acc["status"] = "active"
            acc["start_date"] = datetime.now(timezone.utc).isoformat()
            acc["peak"] = acc["balance"]
            acc["_prev_zone"] = "SAFE"  # reset zone tracking
            log.info("Advancing to Phase 2")
            _queue_prop_alert(f"🟢 **PHASE 1 PASSED!** Profit: {profit_pct:+.1f}%\n🔵 **Phase 2 Started** — Target: 5%, DD limit: 10%, 60 days", severity="HIGH")
        elif phase == "phase_2":
            acc["phase"] = "funded"
            acc["status"] = "active"
            acc["start_date"] = datetime.now(timezone.utc).isoformat()
            log.info("🎉 FUNDED! Entering funded phase")
            _queue_prop_alert(f"🎉 **FUNDED!** Prop challenge complete.\nPhase 2 profit: {profit_pct:+.1f}%\nNow in funded mode — DD limits only.", severity="HIGH")
            try:
                from services.central_alerts import _send_discord
                _send_discord("🎉 **FUNDED!** Prop challenge complete. Entering funded phase.")
            except Exception:
                pass

    save_account(acc)
    return acc


def _get_risk_zone(dd_pct: float) -> str:
    """Map DD percentage to risk zone."""
    for zone, lo, hi in RISK_ZONES:
        if lo <= dd_pct < hi:
            return zone
    return "CRITICAL"


def _queue_prop_alert(message: str, severity: str = "MEDIUM"):
    """Route prop alert through unified central alert system."""
    try:
        from services.central_alerts import alert
        # Extract title from first line
        lines = message.strip().split("\n")
        title = lines[0] if lines else message[:80]
        body = "\n".join(lines[1:]) if len(lines) > 1 else ""
        alert(severity, title, body)
    except Exception as e:
        log.warning(f"Failed to send prop alert: {e}")


def check_zone_transitions(acc: dict) -> dict:
    """Check for risk zone transitions and fire alerts. Only on state changes."""
    total_dd = get_total_dd(acc)
    current_zone = _get_risk_zone(total_dd)
    prev_zone = acc.get("_prev_zone", "SAFE")
    prev_phase = acc.get("_prev_phase", acc.get("phase", "phase_1"))
    daily_dd = abs(get_daily_dd(acc))
    phase_config = PHASES.get(acc.get("phase", "phase_1"), PHASES["phase_1"])

    # Zone transition
    if current_zone != prev_zone:
        zone_order = ["SAFE", "CAUTION", "DANGER", "CRITICAL"]
        curr_idx = zone_order.index(current_zone) if current_zone in zone_order else 0
        prev_idx = zone_order.index(prev_zone) if prev_zone in zone_order else 0

        if curr_idx > prev_idx:
            zone_sev = {"CAUTION": "MEDIUM", "DANGER": "HIGH", "CRITICAL": "CRITICAL"}
            sev = zone_sev.get(current_zone, "MEDIUM")
            emoji = ZONE_EMOJI.get(current_zone, "⚠️")
            _queue_prop_alert(
                f"{emoji} **PROP ZONE: {prev_zone} → {current_zone}**\n"
                f"DD: {total_dd:.1f}% | Pressure: {prop_pressure(acc):.1f}x\n"
                f"Balance: ${acc['balance']:,.0f}",
                severity=sev
            )
        else:
            _queue_prop_alert(
                f"🔄 **PROP RECOVERY: {prev_zone} → {current_zone}**\n"
                f"DD: {total_dd:.1f}% | Pressure: {prop_pressure(acc):.1f}x\n"
                f"Balance: ${acc['balance']:,.0f}",
                severity="LOW"
            )
        log.info(f"Zone transition: {prev_zone} → {current_zone} (DD={total_dd:.1f}%)")

    # Near-fail warning (DD > 4.5% — one-time per crossing)
    if total_dd > 4.5 and acc.get("_near_fail_alerted") != True:
        _queue_prop_alert(
            f"🧨 **PROP NEAR-FAIL WARNING**\n"
            f"DD: {total_dd:.1f}% — approaching {phase_config['max_total_dd_pct']}% limit\n"
            f"Balance: ${acc['balance']:,.0f}",
            severity="CRITICAL"
        )
        acc["_near_fail_alerted"] = True
    elif total_dd < 4.0:
        acc["_near_fail_alerted"] = False  # reset when DD recovers

    # Daily loss breach
    if daily_dd >= phase_config["max_daily_dd_pct"] and acc.get("_daily_breach_today") != datetime.now(timezone.utc).strftime("%Y-%m-%d"):
        _queue_prop_alert(
            f"🔴 **DAILY LOSS BREACH**\n"
            f"Daily DD: {daily_dd:.1f}% >= {phase_config['max_daily_dd_pct']}% limit"
        )
        acc["_daily_breach_today"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    acc["_prev_zone"] = current_zone
    acc["_prev_phase"] = acc.get("phase", "phase_1")
    return acc


def _log_history(acc: dict, event: str):
    """Log prop event to history."""
    entry = {
        "event": event,
        "phase": acc.get("phase"),
        "balance": acc.get("balance"),
        "total_dd_pct": round(get_total_dd(acc), 2),
        "total_trades": acc.get("total_trades"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    PROP_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PROP_HISTORY_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


# =============================================================================
# STATUS REPORT
# =============================================================================

def format_report(acc: dict) -> str:
    phase = acc.get("phase", "phase_1")
    phase_config = PHASES.get(phase, PHASES["phase_1"])
    status = acc.get("status", "active")
    total_dd = get_total_dd(acc)
    daily_dd = get_daily_dd(acc)
    profit_pct = (acc["balance"] - acc["starting_balance"]) / acc["starting_balance"] * 100
    health = get_prop_health(acc)
    pressure = prop_pressure(acc)

    status_emoji = {"active": "🟢", "passed": "✅", "failed": "🔴"}.get(status, "❓")
    target = phase_config.get("profit_target_pct", "∞")

    wr = acc["wins"] / max(acc["total_trades"], 1)

    start = datetime.fromisoformat(acc["start_date"])
    elapsed = (datetime.now(timezone.utc) - start).days
    time_limit = phase_config.get("time_limit_days", "∞")

    lines = [
        f"🏦 Prop Challenge — {phase_config['name']} {status_emoji}",
        "",
        f"Balance: ${acc['balance']:,.0f} / ${acc['starting_balance']:,.0f}",
        f"Profit: {profit_pct:+.1f}% (target: {target}%)",
        f"Total DD: {total_dd:.1f}% (limit: {phase_config['max_total_dd_pct']}%)",
        f"Daily DD: {daily_dd:+.1f}% (limit: {phase_config['max_daily_dd_pct']}%)",
        f"Health: {health:.2f} | Pressure: {pressure:.1f}x",
        f"Trades: {acc['total_trades']} (WR: {wr:.0%})",
        f"Day: {elapsed} / {time_limit}",
    ]

    return "\n".join(lines)


# =============================================================================
# DAEMON / CLI
# =============================================================================

def run_cycle():
    acc = load_account()
    acc = process_trades(acc)
    acc = check_phase_status(acc)
    acc = check_zone_transitions(acc)
    save_account(acc)
    return acc


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    if args.reset:
        reset_account()
        print("Prop account reset.")
        return

    if args.daemon:
        running = True
        def stop(s, f): nonlocal running; running = False
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        log.info("Prop tracker daemon started (5-min cycle)")
        while running:
            acc = run_cycle()
            log.info(f"Prop: ${acc['balance']:,.0f} DD={get_total_dd(acc):.1f}% pressure={prop_pressure(acc):.1f}x phase={acc['phase']} status={acc['status']}")
            for _ in range(300):  # 5 min
                if not running:
                    break
                time.sleep(1)
    else:
        acc = run_cycle()
        print(format_report(acc))


if __name__ == "__main__":
    main()
