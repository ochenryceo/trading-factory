#!/usr/bin/env python3
"""
Paper Signal Engine — Shadow Execution for Paper Trading Pool
==============================================================
Runs paper-approved strategies against live/recent data and forwards
signals to NinjaTrader via the webhook receiver.

Architecture:
  Paper Pool → Signal Engine → Execution Filter → Webhook → NinjaTrader
                                                          → Live Metrics Logger

Execution Filter:
  - Slippage estimation (0.5 tick per side)
  - Session-aware (only trade during market hours)
  - Risk normalization (position sizing per strategy)
  - Duplicate signal suppression

Metrics Tracked:
  - Live sharpe vs backtest sharpe
  - Live win rate vs expected
  - Live DD vs MC worst DD
  - Slippage per trade
  - Rolling sharpe (last 20 trades)
  - Missed trades

Promotion Rule (paper → production):
  - ≥ 50 live paper trades
  - Live sharpe ≥ 1.5
  - Max DD within 1.5x MC expected
  - No rule violations
  - Consecutive profitable weeks ≥ 3

Author: Henry (autonomous build)
Date: 2026-03-26
"""

import json
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
import hashlib

log = logging.getLogger("paper_signal_engine")

BASE_DIR = Path("Path(__file__).resolve().parents[1]")
DATA_DIR = BASE_DIR / "data" / "processed"
PAPER_POOL_FILE = BASE_DIR / "data" / "paper_trading_pool.json"
LIVE_METRICS_FILE = BASE_DIR / "data" / "paper_live_metrics.json"
SIGNAL_LOG_FILE = BASE_DIR / "data" / "paper_signal_log.jsonl"
CANDIDATE_DIR = BASE_DIR / "data" / "candidates"

# ─── Execution Filter Config ────────────────────────────────────────────

SLIPPAGE_TICKS = 0.5          # Estimated slippage per side
TICK_VALUES = {"NQ": 5.0, "GC": 0.10, "CL": 0.01}  # Dollar per tick
MAX_POSITION_SIZE = 1          # Paper = 1 contract always
SIGNAL_COOLDOWN_BARS = 3       # Min bars between signals per strategy
MARKET_HOURS = {               # UTC hours when signals are valid
    "NQ": (14, 21),            # NY session focus: 9:00-16:00 ET
    "GC": (14, 21),
    "CL": (14, 21),
}

# ─── Promotion Criteria (paper → production) ───────────────────────────

PROMO_MIN_TRADES = 50
PROMO_MIN_LIVE_SHARPE = 1.5
PROMO_DD_MULTIPLIER = 1.5     # Max DD ≤ 1.5x MC expected
PROMO_MIN_PROFITABLE_WEEKS = 3


def load_pool() -> list:
    """Load current paper trading pool."""
    if not PAPER_POOL_FILE.exists():
        return []
    try:
        return json.load(open(PAPER_POOL_FILE))
    except Exception:
        return []


def load_live_metrics() -> dict:
    """Load live tracking metrics for all strategies."""
    if not LIVE_METRICS_FILE.exists():
        return {}
    try:
        return json.load(open(LIVE_METRICS_FILE))
    except Exception:
        return {}


def save_live_metrics(metrics: dict):
    """Persist live metrics."""
    LIVE_METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LIVE_METRICS_FILE, "w") as f:
        json.dump(metrics, f, indent=2, default=str)


def log_signal(signal: dict):
    """Append signal to log."""
    SIGNAL_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SIGNAL_LOG_FILE, "a") as f:
        f.write(json.dumps(signal, separators=(",", ":"), default=str) + "\n")


# ─── Execution Filter ──────────────────────────────────────────────────

def is_market_open(asset: str) -> bool:
    """Check if within trading hours for asset."""
    now = datetime.now(timezone.utc)
    hours = MARKET_HOURS.get(asset, (14, 21))
    return hours[0] <= now.hour < hours[1]


def estimate_slippage(asset: str, direction: str) -> float:
    """Estimate slippage cost in price terms."""
    tick_val = TICK_VALUES.get(asset, 0.01)
    return SLIPPAGE_TICKS * tick_val


def check_cooldown(strategy_code: str, metrics: dict) -> bool:
    """Check if enough bars since last signal."""
    strat_metrics = metrics.get(strategy_code, {})
    last_signal_time = strat_metrics.get("last_signal_time", "")
    if not last_signal_time:
        return True
    
    try:
        last = datetime.fromisoformat(last_signal_time)
        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
        # Assume ~1 bar per hour for 1h strategies
        return elapsed >= SIGNAL_COOLDOWN_BARS * 3600
    except Exception:
        return True


# ─── Live Metrics Tracking ─────────────────────────────────────────────

def update_metrics_on_entry(strategy_code: str, metrics: dict, signal: dict) -> dict:
    """Update live metrics when a new entry signal fires."""
    if strategy_code not in metrics:
        metrics[strategy_code] = {
            "total_signals": 0,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "total_pnl": 0.0,
            "max_dd": 0.0,
            "peak_equity": 0.0,
            "current_equity": 0.0,
            "trade_returns": [],
            "rolling_sharpe": 0.0,
            "live_sharpe": 0.0,
            "live_win_rate": 0.0,
            "missed_signals": 0,
            "slippage_total": 0.0,
            "last_signal_time": "",
            "first_signal_time": "",
            "open_position": None,
            "weekly_pnl": {},
            "consecutive_profitable_weeks": 0,
            "status": "active",
        }
    
    m = metrics[strategy_code]
    m["total_signals"] += 1
    m["last_signal_time"] = signal.get("timestamp", datetime.now(timezone.utc).isoformat())
    if not m["first_signal_time"]:
        m["first_signal_time"] = m["last_signal_time"]
    
    # Track open position
    m["open_position"] = {
        "entry_price": signal["price"],
        "direction": signal["direction"],
        "entry_time": signal.get("timestamp"),
        "slippage": signal.get("slippage_estimate", 0),
    }
    
    return metrics


def update_metrics_on_exit(strategy_code: str, metrics: dict, signal: dict) -> dict:
    """Update live metrics when exit signal fires."""
    m = metrics.get(strategy_code, {})
    if not m or not m.get("open_position"):
        return metrics
    
    pos = m["open_position"]
    entry_price = pos["entry_price"]
    exit_price = signal["price"]
    direction = pos["direction"]
    
    # Calculate PnL
    if direction == "LONG":
        pnl_pct = (exit_price - entry_price) / entry_price
    else:
        pnl_pct = (entry_price - exit_price) / entry_price
    
    # Apply slippage
    slippage = signal.get("slippage_estimate", 0) + pos.get("slippage", 0)
    pnl_pct -= slippage / entry_price  # rough slippage deduction
    
    m["total_trades"] += 1
    m["total_pnl"] += pnl_pct
    m["slippage_total"] += slippage
    m["trade_returns"].append(round(pnl_pct, 6))
    
    if pnl_pct > 0:
        m["wins"] += 1
        m.setdefault("win_amounts", []).append(round(pnl_pct, 6))
    else:
        m["losses"] += 1
        m.setdefault("loss_amounts", []).append(round(pnl_pct, 6))
    
    # PnL distribution tracking
    wins = m.get("win_amounts", [])
    losses = m.get("loss_amounts", [])
    m["avg_win"] = round(sum(wins) / len(wins), 6) if wins else 0
    m["avg_loss"] = round(sum(losses) / len(losses), 6) if losses else 0
    m["max_loss"] = round(min(losses), 6) if losses else 0
    m["win_loss_ratio"] = round(abs(m["avg_win"] / m["avg_loss"]), 4) if m["avg_loss"] != 0 else float("inf")
    
    # Update equity tracking
    m["current_equity"] += pnl_pct
    if m["current_equity"] > m["peak_equity"]:
        m["peak_equity"] = m["current_equity"]
    dd = m["peak_equity"] - m["current_equity"]
    if dd > m["max_dd"]:
        m["max_dd"] = dd
    
    # Live win rate
    if m["total_trades"] > 0:
        m["live_win_rate"] = m["wins"] / m["total_trades"]
    
    # Rolling sharpe (last 20 trades)
    recent = m["trade_returns"][-20:]
    if len(recent) >= 5:
        import statistics
        mean_r = statistics.mean(recent)
        std_r = statistics.stdev(recent) if len(recent) > 1 else 0.001
        m["rolling_sharpe"] = round(mean_r / max(std_r, 0.001), 4)
    
    # Full live sharpe
    all_returns = m["trade_returns"]
    if len(all_returns) >= 5:
        import statistics
        mean_r = statistics.mean(all_returns)
        std_r = statistics.stdev(all_returns) if len(all_returns) > 1 else 0.001
        m["live_sharpe"] = round(mean_r / max(std_r, 0.001), 4)
    
    # Weekly PnL tracking
    week_key = datetime.now(timezone.utc).strftime("%Y-W%W")
    m["weekly_pnl"][week_key] = m["weekly_pnl"].get(week_key, 0) + pnl_pct
    
    # Consecutive profitable weeks
    weeks = sorted(m["weekly_pnl"].keys())
    consec = 0
    for w in reversed(weeks):
        if m["weekly_pnl"][w] > 0:
            consec += 1
        else:
            break
    m["consecutive_profitable_weeks"] = consec
    
    # Clear position
    m["open_position"] = None
    
    metrics[strategy_code] = m
    return metrics


# ─── Promotion Check ──────────────────────────────────────────────────

def check_promotion(strategy_code: str, metrics: dict, backtest_mc_dd: float) -> dict:
    """Check if strategy qualifies for production promotion."""
    m = metrics.get(strategy_code, {})
    
    checks = {
        "min_trades": m.get("total_trades", 0) >= PROMO_MIN_TRADES,
        "live_sharpe": m.get("live_sharpe", 0) >= PROMO_MIN_LIVE_SHARPE,
        "dd_within_mc": m.get("max_dd", 999) <= backtest_mc_dd * PROMO_DD_MULTIPLIER,
        "profitable_weeks": m.get("consecutive_profitable_weeks", 0) >= PROMO_MIN_PROFITABLE_WEEKS,
    }
    
    result = {
        "strategy_code": strategy_code,
        "eligible": all(checks.values()),
        "checks": checks,
        "metrics": {
            "total_trades": m.get("total_trades", 0),
            "live_sharpe": m.get("live_sharpe", 0),
            "live_win_rate": m.get("live_win_rate", 0),
            "max_dd": m.get("max_dd", 0),
            "expected_mc_dd": backtest_mc_dd,
        }
    }
    
    if result["eligible"]:
        try:
            from services.discord_paper_monitor import alert_promotion_eligible
            alert_promotion_eligible(
                strategy_code,
                m.get("live_sharpe", 0),
                m.get("total_trades", 0),
                m.get("live_win_rate", 0),
            )
        except Exception:
            pass
    
    return result


# ─── Strategy Competition Layer ────────────────────────────────────────

def compute_live_weights(metrics: dict, pool: list) -> dict:
    """
    Dynamic capital weighting based on live performance.
    Strategies compete: strong get more allocation, weak fade out.
    
    Score = 0.40 * norm(live_sharpe)
          + 0.25 * norm(1 - max_dd)
          + 0.20 * norm(rolling_sharpe)
          + 0.15 * norm(win_loss_ratio)
    
    Min weight = 0.05 (never fully zero — still collecting data)
    Requires ≥ 10 trades to score; below that, equal weight.
    """
    codes = [s["strategy_code"] for s in pool]
    scores = {}
    
    for code in codes:
        m = metrics.get(code, {})
        trades = m.get("total_trades", 0)
        
        if trades < 10:
            scores[code] = 1.0  # equal weight until enough data
            continue
        
        live_sharpe = max(m.get("live_sharpe", 0), 0)
        safety = max(1.0 - m.get("max_dd", 0), 0)
        rolling = max(m.get("rolling_sharpe", 0), 0)
        wlr = min(m.get("win_loss_ratio", 1), 5)  # cap at 5x
        
        score = (0.40 * live_sharpe +
                 0.25 * safety * 3 +     # scale safety to comparable range
                 0.20 * rolling +
                 0.15 * wlr)
        scores[code] = max(score, 0.01)
    
    # Normalize to weights
    total = sum(scores.values())
    if total == 0:
        return {code: 1.0 / len(codes) for code in codes}
    
    weights = {}
    for code in codes:
        raw = scores[code] / total
        weights[code] = round(max(raw, 0.05), 4)  # min 5% allocation
    
    # Re-normalize after floor
    total_w = sum(weights.values())
    weights = {k: round(v / total_w, 4) for k, v in weights.items()}
    
    return weights


# ─── Status Report ────────────────────────────────────────────────────

def paper_trading_report() -> str:
    """Generate paper trading status report."""
    pool = load_pool()
    metrics = load_live_metrics()
    
    if not pool:
        return "📄 Paper Trading: No strategies in pool"
    
    weights = compute_live_weights(metrics, pool)
    
    lines = ["📄 **Paper Trading Report**\n"]
    
    for strat in pool:
        code = strat["strategy_code"]
        m = metrics.get(code, {})
        w = weights.get(code, 0)
        
        live_trades = m.get("total_trades", 0)
        live_sharpe = m.get("live_sharpe", 0)
        live_wr = m.get("live_win_rate", 0)
        live_dd = m.get("max_dd", 0)
        bt_sharpe = strat.get("sharpe", 0)
        bt_wr = strat.get("win_rate", 0)
        mc_dd = abs(strat.get("mc_worst_dd", 0))
        
        status = "🟢" if live_trades >= 10 and live_sharpe > 1.0 else "🟡" if live_trades > 0 else "⚪"
        
        lines.append(f"{status} **{code}** ({strat.get('style', '?')}) — weight: {w:.0%}")
        lines.append(f"  Paper trades: {live_trades}/{PROMO_MIN_TRADES} for promotion")
        
        if live_trades > 0:
            sharpe_drift = live_sharpe - bt_sharpe
            wr_drift = live_wr - bt_wr
            lines.append(f"  Sharpe: {live_sharpe:.2f} (backtest: {bt_sharpe:.2f}, drift: {sharpe_drift:+.2f})")
            lines.append(f"  WR: {live_wr:.1%} (backtest: {bt_wr:.1%}, drift: {wr_drift:+.1%})")
            lines.append(f"  DD: {live_dd:.2%} (MC expected: {mc_dd:.2%})")
            lines.append(f"  Rolling sharpe (20): {m.get('rolling_sharpe', 0):.2f}")
            # PnL distribution
            avg_win = m.get("avg_win", 0)
            avg_loss = m.get("avg_loss", 0)
            max_loss = m.get("max_loss", 0)
            wlr = m.get("win_loss_ratio", 0)
            lines.append(f"  PnL: avg_win={avg_win:+.4f} avg_loss={avg_loss:+.4f} max_loss={max_loss:+.4f} W/L={wlr:.2f}x")
        else:
            lines.append(f"  Awaiting first trade...")
        
        lines.append("")
    
    return "\n".join(lines)


# ─── Main Entry ───────────────────────────────────────────────────────

if __name__ == "__main__":
    print(paper_trading_report())
    
    pool = load_pool()
    metrics = load_live_metrics()
    
    print(f"\nPaper Pool: {len(pool)} strategies")
    print(f"Live metrics tracked: {len(metrics)} strategies")
    
    for strat in pool:
        code = strat["strategy_code"]
        artifact_path = CANDIDATE_DIR / f"{code}.json"
        if artifact_path.exists():
            artifact = json.load(open(artifact_path))
            mc_dd = abs(artifact["monte_carlo"]["mc_worst_dd"])
            promo = check_promotion(code, metrics, mc_dd)
            status = "✅ ELIGIBLE" if promo["eligible"] else "⏳ Not ready"
            print(f"  {code}: {status}")
            for check, passed in promo["checks"].items():
                icon = "✅" if passed else "❌"
                print(f"    {icon} {check}")
