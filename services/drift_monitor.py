#!/usr/bin/env python3
"""
Live Drift Monitor — Trading Factory
=====================================
Watches paper trading strategies on NinjaTrader and detects when live behavior
diverges from backtested expectations. Classifies each strategy as OK, WARMUP,
REDUCE, or KILL and outputs weight multipliers for Brain integration.

Usage:
    python drift_monitor.py            # one-shot check, print summary, exit
    python drift_monitor.py --daemon   # check every 15 minutes
    python drift_monitor.py --report   # human-readable markdown report

Data flow:
    trades.json → per-strategy analysis → drift_status.json + drift_history.jsonl
"""

import argparse
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
TRADES_FILE = DATA_DIR / "paper_trading" / "trades.json"
EXPECTATIONS_FILE = DATA_DIR / "drift_expectations.json"
STATUS_FILE = DATA_DIR / "drift_status.json"
HISTORY_FILE = DATA_DIR / "drift_history.jsonl"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLLING_WINDOW_TRADES = 50        # max trades per strategy in rolling window
ROLLING_WINDOW_DAYS = 7           # or last N days, whichever is smaller
WARMUP_THRESHOLD = 20             # minimum trades before graduating from WARMUP
DAEMON_INTERVAL_SEC = 15 * 60     # 15 minutes
MONITORED_STRATEGIES = [
    "LockedProductionV1",
    "NRG3004C1",
    "TFG3003C1",
]

# ---------------------------------------------------------------------------
# Default expectations (written to drift_expectations.json on first run)
# ---------------------------------------------------------------------------
DEFAULT_EXPECTATIONS: dict[str, dict[str, Any]] = {
    "LockedProductionV1": {
        "mean_return_per_trade": 0.005,
        "std_return_per_trade": 0.02,
        "expected_win_rate": 0.57,
        "expected_max_dd_pct": 6.0,
        "expected_sharpe": 2.08,
        "expected_profit_factor": 2.08,
        "expected_trades_per_month": 2.5,
        "mc_p95_dd": 0.10,
        "source": "backtest",
    },
    "NRG3004C1": {
        "mean_return_per_trade": 0.003,
        "std_return_per_trade": 0.015,
        "expected_win_rate": 0.50,
        "expected_max_dd_pct": 10.0,
        "expected_sharpe": 1.5,
        "expected_profit_factor": 1.5,
        "expected_trades_per_month": 10,
        "mc_p95_dd": 0.15,
        "source": "estimate",
    },
    "TFG3003C1": {
        "mean_return_per_trade": 0.003,
        "std_return_per_trade": 0.015,
        "expected_win_rate": 0.50,
        "expected_max_dd_pct": 10.0,
        "expected_sharpe": 1.5,
        "expected_profit_factor": 1.5,
        "expected_trades_per_month": 8,
        "mc_p95_dd": 0.15,
        "source": "estimate",
    },
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [drift] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("drift_monitor")

# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------
_shutdown = False


def _handle_signal(signum: int, _frame: Any) -> None:
    global _shutdown
    log.info("Received signal %s — shutting down", signum)
    _shutdown = True


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON atomically via temp file + rename."""
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, default=str)
        f.write("\n")
    tmp.rename(path)


def _append_jsonl(path: Path, record: dict) -> None:
    """Append a single JSON line."""
    with open(path, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def _load_json(path: Path, default: Any = None) -> Any:
    """Load JSON file, return default if missing or corrupt."""
    if not path.exists():
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        log.warning("Failed to read %s: %s", path, e)
        return default


# ---------------------------------------------------------------------------
# Expectations management
# ---------------------------------------------------------------------------

def load_expectations() -> dict[str, dict[str, Any]]:
    """Load or initialise the expectations file."""
    data = _load_json(EXPECTATIONS_FILE)
    if data and isinstance(data, dict):
        return data
    # First run — seed defaults
    log.info("Creating default drift_expectations.json")
    EXPECTATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(EXPECTATIONS_FILE, DEFAULT_EXPECTATIONS)
    return DEFAULT_EXPECTATIONS


# ---------------------------------------------------------------------------
# Trade loading & filtering
# ---------------------------------------------------------------------------

def load_trades() -> list[dict]:
    """Load all trades from the paper trading JSON file."""
    raw = _load_json(TRADES_FILE, default=[])
    if not isinstance(raw, list):
        log.warning("trades.json is not a list — treating as empty")
        return []
    return raw


def filter_trades(
    trades: list[dict],
    strategy: str,
    max_trades: int = ROLLING_WINDOW_TRADES,
    max_days: int = ROLLING_WINDOW_DAYS,
) -> list[dict]:
    """
    Return the rolling window of completed (exit) trades for a strategy.
    Window = min(last *max_trades* trades, last *max_days* days).
    """
    # Only completed trades (exits with pnl)
    strat_trades = [
        t for t in trades
        if t.get("system") == strategy
        and t.get("action") == "exit"
        and t.get("pnl_dollars") is not None
    ]

    # Sort by timestamp ascending
    strat_trades.sort(key=lambda t: t.get("timestamp", ""))

    # Time filter
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_days)
    cutoff_iso = cutoff.isoformat()
    strat_trades = [
        t for t in strat_trades
        if t.get("timestamp", "") >= cutoff_iso
    ]

    # Take last N
    return strat_trades[-max_trades:]


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------

def compute_metrics(
    trades: list[dict],
    expectations: dict[str, Any],
) -> dict[str, Any]:
    """
    Compute all drift metrics for a single strategy's trade window.
    Returns a dict of metric values; handles zero-trade case gracefully.
    """
    n = len(trades)
    exp = expectations

    # --- No trades → pure warmup shell ---
    if n == 0:
        return {
            "live_trades": 0,
            "live_win_rate": 0.0,
            "live_mean_return": 0.0,
            "live_total_pnl": 0.0,
            "live_max_dd": 0.0,
            "z_score": 0.0,
            "dd_ratio": 0.0,
            "freq_deviation": 1.0,   # fully deviant — no trades at all
            "wr_drop": 0.0,
            "consecutive_losses": 0,
        }

    # PnL series
    pnls = [float(t.get("pnl_dollars", 0)) for t in trades]
    total_pnl = sum(pnls)

    # Returns (as fraction of notional — approximate using entry_price * quantity * $20/pt for NQ)
    returns = []
    for t in trades:
        entry = float(t.get("entry_price", 0))
        qty = int(t.get("quantity", 1))
        pnl = float(t.get("pnl_dollars", 0))
        # NQ point value = $20 per point per contract
        notional = entry * qty * 20 if entry > 0 else 1
        returns.append(pnl / notional if notional else 0)

    mean_ret = sum(returns) / n if n else 0

    # Win rate
    wins = sum(1 for p in pnls if p > 0)
    win_rate = wins / n

    # Max drawdown (from cumulative PnL high-water mark, as % of peak equity)
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cum += p
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd
    # Express dd as percentage (of peak or expected max dd baseline)
    # Use absolute dollar dd vs expected_max_dd_pct (which is % based)
    # For comparability, express live_max_dd as a percentage too:
    # We'll use peak equity or a baseline of $100k account
    account_base = max(peak, 100_000)  # conservative baseline
    live_max_dd_pct = (max_dd / account_base * 100) if account_base > 0 else 0

    # --- Drift metrics ---

    # 1. Return Z-Score
    exp_mean = exp.get("mean_return_per_trade", 0)
    exp_std = exp.get("std_return_per_trade", 1)
    z_score = (mean_ret - exp_mean) / exp_std if exp_std > 0 else 0

    # 2. Drawdown Breach Ratio
    exp_dd = exp.get("expected_max_dd_pct", 10)
    dd_ratio = live_max_dd_pct / exp_dd if exp_dd > 0 else 0

    # 3. Trade Frequency Deviation
    # Compute actual trades per month from the window timespan
    if n >= 2:
        first_ts = trades[0].get("timestamp", "")
        last_ts = trades[-1].get("timestamp", "")
        try:
            t0 = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            span_days = max((t1 - t0).total_seconds() / 86400, 1)
            live_freq = n / span_days * 30  # trades per month
        except (ValueError, TypeError):
            live_freq = 0
    else:
        live_freq = 0

    exp_freq = exp.get("expected_trades_per_month", 1)
    freq_deviation = abs(live_freq - exp_freq) / exp_freq if exp_freq > 0 else 0

    # 4. Win Rate Drop (positive = drop)
    exp_wr = exp.get("expected_win_rate", 0.5)
    wr_drop = exp_wr - win_rate  # positive means live WR is lower

    # 5. Consecutive Loss Streak
    max_consec = 0
    current_consec = 0
    for p in pnls:
        if p <= 0:
            current_consec += 1
            max_consec = max(max_consec, current_consec)
        else:
            current_consec = 0

    return {
        "live_trades": n,
        "live_win_rate": round(win_rate, 4),
        "live_mean_return": round(mean_ret, 6),
        "live_total_pnl": round(total_pnl, 2),
        "live_max_dd": round(live_max_dd_pct, 4),
        "z_score": round(z_score, 4),
        "dd_ratio": round(dd_ratio, 4),
        "freq_deviation": round(freq_deviation, 4),
        "wr_drop": round(wr_drop, 4),
        "consecutive_losses": max_consec,
    }


# ---------------------------------------------------------------------------
# Classification engine
# ---------------------------------------------------------------------------

# Graceful degradation ladder (not binary)
STATUS_EMOJI = {
    "OK": "✅",
    "WARMUP": "⏳",
    "REDUCE": "⚠️",
    "STRONG_REDUCE": "🟠",
    "SEVERE": "🔴",
    "KILL": "🛑",
    "RECOVERING": "🔄",
}

WEIGHT_MAP = {
    "OK": 1.0,
    "WARMUP": 0.5,
    "REDUCE": 0.75,
    "STRONG_REDUCE": 0.5,
    "SEVERE": 0.25,
    "KILL": 0.0,
    "RECOVERING": 0.3,
}

RECOMMENDATIONS = {
    "OK": "Continue as normal",
    "WARMUP": "Building confidence — half weight until {threshold} trades",
    "REDUCE": "Mild drift — reduce to 75%",
    "STRONG_REDUCE": "Significant drift — reduce to 50%",
    "SEVERE": "Major drift — reduce to 25%, review urgently",
    "KILL": "Critical drift — halt trading immediately",
    "RECOVERING": "Previously killed, recovery detected — cautious re-entry at 30%",
}

# Recovery + cooldown tracking
KILL_COOLDOWN_HOURS = 24
KILL_STATE_PATH = BASE_DIR / "data" / "drift_kill_state.json"

# Portfolio-level kill switch
PORTFOLIO_DD_REDUCE = 0.15   # scale all weights by 0.5
PORTFOLIO_DD_KILL = 0.25     # halt everything


def _load_kill_state() -> dict:
    """Load kill/recovery state for strategies."""
    if KILL_STATE_PATH.exists():
        try:
            with open(KILL_STATE_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_kill_state(state: dict):
    """Save kill/recovery state."""
    KILL_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(KILL_STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def classify(metrics: dict[str, Any]) -> str:
    """
    Classify strategy health with graceful degradation ladder.
    Order: KILL → SEVERE → STRONG_REDUCE → REDUCE → WARMUP → OK
    Recovery logic: killed strategies can come back after cooldown.
    """
    z = metrics["z_score"]
    dd = metrics["dd_ratio"]
    consec = metrics["consecutive_losses"]
    freq = metrics["freq_deviation"]
    wr = metrics["wr_drop"]
    n = metrics["live_trades"]
    strategy = metrics.get("strategy_code", "")

    # No trades at all — pure warmup
    if n == 0:
        return "WARMUP"

    # Check recovery state — if previously killed, check cooldown
    kill_state = _load_kill_state()
    strat_kill = kill_state.get(strategy, {})
    if strat_kill.get("killed"):
        killed_at = strat_kill.get("killed_at", "")
        try:
            killed_time = datetime.fromisoformat(killed_at)
            hours_since = (datetime.now(timezone.utc) - killed_time).total_seconds() / 3600
            if hours_since < KILL_COOLDOWN_HOURS:
                # Still in cooldown — stay killed
                return "KILL"
            else:
                # Cooldown expired — check if metrics have recovered
                if z > -0.5 and dd < 1.0 and consec < 3:
                    # Recovery detected — cautious re-entry
                    strat_kill["killed"] = False
                    strat_kill["recovered_at"] = datetime.now(timezone.utc).isoformat()
                    kill_state[strategy] = strat_kill
                    _save_kill_state(kill_state)
                    log.info(f"  🔄 {strategy}: Recovery detected after {hours_since:.0f}h cooldown")
                    try:
                        from services.central_alerts import alert_recovery
                        alert_recovery(strategy)
                    except Exception:
                        pass
                    return "RECOVERING"
                else:
                    return "KILL"  # still bad after cooldown
        except Exception:
            pass

    # KILL — extreme drift
    if z < -2.5 or dd > 2.0 or consec >= 6:
        # Record kill time for recovery logic
        reason = f"z={z:.2f} dd={dd:.2f} consec={consec}"
        kill_state[strategy] = {
            "killed": True,
            "killed_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
        }
        _save_kill_state(kill_state)
        try:
            from services.central_alerts import alert_kill
            alert_kill(strategy, reason)
        except Exception:
            pass
        return "KILL"

    # SEVERE — near-kill
    if z < -2 or dd > 1.5 or consec >= 5:
        return "SEVERE"

    # STRONG_REDUCE
    if z < -1.5 or dd > 1.3 or consec >= 4 or (freq > 0.5 and wr > 0.15):
        return "STRONG_REDUCE"

    # REDUCE — mild drift
    if z < -1 or dd > 1.2 or freq > 0.5 or wr > 0.20:
        return "REDUCE"

    # WARMUP — not enough data
    if n < WARMUP_THRESHOLD:
        return "WARMUP"

    return "OK"


def compute_portfolio_scale(strategy_statuses: dict) -> float:
    """
    Portfolio-level kill switch.
    Compute combined portfolio DD and return global scale factor.
    """
    # Load all trade PnLs across all strategies
    trades = _load_trades()
    if not trades:
        return 1.0

    # Compute portfolio equity curve
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in sorted(trades, key=lambda x: x.get("timestamp", "")):
        pnl = t.get("pnl_dollars", 0)
        if t.get("action") == "exit" and pnl != 0:
            equity += pnl
            if equity > peak:
                peak = equity
            dd = (peak - equity) / max(peak, 1) if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

    if max_dd > PORTFOLIO_DD_KILL:
        log.error(f"🛑 PORTFOLIO KILL SWITCH: DD={max_dd:.1%} > {PORTFOLIO_DD_KILL:.0%}")
        try:
            from services.central_alerts import alert_portfolio_dd
            alert_portfolio_dd(max_dd, 0.0)
        except Exception:
            pass
        return 0.0
    elif max_dd > PORTFOLIO_DD_REDUCE:
        log.warning(f"⚠️ PORTFOLIO STRESS: DD={max_dd:.1%} > {PORTFOLIO_DD_REDUCE:.0%} — scaling to 50%")
        try:
            from services.central_alerts import alert_portfolio_dd
            alert_portfolio_dd(max_dd, 0.5)
        except Exception:
            pass
        return 0.5

    return 1.0


def _load_trades() -> list:
    """Load trades from paper trading JSON."""
    if not TRADES_FILE.exists():
        return []
    try:
        with open(TRADES_FILE) as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Correlation Spike Detector (V1 — portfolio-level risk)
# ---------------------------------------------------------------------------

CORR_WINDOW = 50        # rolling window of trades per strategy
CORR_WARN = 0.7         # average pairwise corr above this → scale down
CORR_DANGER = 0.85      # above this → aggressive scale

def compute_correlation_scale(trades: list) -> tuple[float, float]:
    """
    Compute average pairwise correlation of rolling returns across strategies.
    Returns (scale_factor, avg_correlation).
    
    Uses last CORR_WINDOW exit trades per strategy to build return series,
    then computes pairwise correlation of PnL sequences (aligned by trade index).
    """
    # Group exit PnLs by strategy (last N trades)
    strat_pnls: dict[str, list[float]] = {}
    for strat in MONITORED_STRATEGIES:
        exits = [
            t.get("pnl_dollars", 0)
            for t in trades
            if t.get("system", t.get("strategy", "")) == strat
            and t.get("action") == "exit"
            and t.get("pnl_dollars", 0) != 0
        ]
        if exits:
            strat_pnls[strat] = exits[-CORR_WINDOW:]

    # Need at least 2 strategies with 5+ trades each
    active = {k: v for k, v in strat_pnls.items() if len(v) >= 5}
    if len(active) < 2:
        return 1.0, 0.0

    # Align by index (pad shorter to longest with 0)
    max_len = max(len(v) for v in active.values())
    names = list(active.keys())
    
    # Compute pairwise correlations
    import numpy as np
    corrs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a = active[names[i]]
            b = active[names[j]]
            # Use overlapping length
            min_len = min(len(a), len(b))
            if min_len < 5:
                continue
            arr_a = np.array(a[-min_len:], dtype=np.float64)
            arr_b = np.array(b[-min_len:], dtype=np.float64)
            # Avoid zero-variance
            if np.std(arr_a) < 1e-10 or np.std(arr_b) < 1e-10:
                continue
            corr = np.corrcoef(arr_a, arr_b)[0, 1]
            if not np.isnan(corr):
                corrs.append(corr)

    if not corrs:
        return 1.0, 0.0

    avg_corr = float(np.mean(corrs))

    if avg_corr > CORR_DANGER:
        log.warning(f"🔴 CORRELATION SPIKE: avg={avg_corr:.2f} > {CORR_DANGER} — scaling to 50%")
        return 0.5, avg_corr
    elif avg_corr > CORR_WARN:
        log.warning(f"⚠️ CORRELATION HIGH: avg={avg_corr:.2f} > {CORR_WARN} — scaling to 70%")
        return 0.7, avg_corr

    return 1.0, avg_corr


# ---------------------------------------------------------------------------
# Execution Drift Tracker (V1 — silent killer detector)
# ---------------------------------------------------------------------------

SLIPPAGE_WARN = 0.002    # 0.2% slippage threshold
MISSED_RATE_WARN = 0.10  # 10% missed trade threshold
LATENCY_WARN_SEC = 60    # 60 second latency threshold

def compute_execution_score(trades: list, strategy: str) -> dict:
    """
    V1 execution quality scoring per strategy.
    Tracks: slippage estimate, fill latency, missed trade rate.
    
    Returns dict with score (0-1), slippage, latency, missed_rate.
    
    Since we don't have signal timestamps from NinjaTrader yet,
    V1 focuses on what we CAN measure from trade data:
    - Slippage: entry_price vs expected (not available yet → placeholder)
    - Fill gaps: time between entry and exit consistency
    - Trade frequency: actual vs expected (already in drift metrics)
    """
    strat_trades = [
        t for t in trades
        if t.get("system", t.get("strategy", "")) == strategy
    ]

    if len(strat_trades) < 3:
        return {
            "execution_score": 1.0,
            "avg_slippage_pct": 0.0,
            "avg_latency_sec": 0.0,
            "missed_rate": 0.0,
            "trade_gaps_consistent": True,
            "note": "Insufficient trades for execution analysis",
        }

    score = 1.0
    
    # --- Slippage estimate ---
    # Compare entry vs exit prices for round-trip cost analysis
    # V1: estimate slippage from spread between consecutive entry/exit pairs
    entries = [t for t in strat_trades if t.get("action") == "entry"]
    exits = [t for t in strat_trades if t.get("action") == "exit"]
    
    slippages = []
    for entry in entries:
        ep = entry.get("entry_price", 0)
        if ep > 0:
            # Estimate: compare to instrument's typical tick value
            # NQ tick = 0.25 ($5), reasonable slippage = 1-2 ticks
            # For now, track raw entry prices for trend detection
            slippages.append(ep)
    
    avg_slippage_pct = 0.0  # will be populated when we have expected prices
    
    # --- Trade gap consistency ---
    # If gaps between trades become irregular, execution may be degrading
    timestamps = []
    for t in sorted(strat_trades, key=lambda x: x.get("timestamp", "")):
        ts = t.get("timestamp", "")
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                timestamps.append(dt)
            except Exception:
                pass

    gaps_sec = []
    for i in range(1, len(timestamps)):
        gap = (timestamps[i] - timestamps[i - 1]).total_seconds()
        if gap > 0:
            gaps_sec.append(gap)

    avg_latency = 0.0
    gaps_consistent = True
    if gaps_sec:
        import numpy as np
        avg_latency = float(np.mean(gaps_sec))
        gap_std = float(np.std(gaps_sec))
        # If std > 3x mean, gaps are very irregular
        if avg_latency > 0 and gap_std > avg_latency * 3:
            gaps_consistent = False
            score -= 0.15

    # --- Missed trade detection ---
    # V1: compare actual trade count vs expected frequency
    # (already handled by drift monitor freq_deviation, so just reference it)
    missed_rate = 0.0  # will integrate with signal log when available

    # --- Score penalties ---
    if avg_slippage_pct > SLIPPAGE_WARN:
        score -= 0.2
    if missed_rate > MISSED_RATE_WARN:
        score -= 0.3
    if avg_latency > LATENCY_WARN_SEC and len(gaps_sec) > 5:
        # Only penalize if we have enough data points
        score -= 0.1

    return {
        "execution_score": round(max(0.0, min(1.0, score)), 3),
        "avg_slippage_pct": round(avg_slippage_pct, 6),
        "avg_latency_sec": round(avg_latency, 1),
        "missed_rate": round(missed_rate, 4),
        "trade_gaps_consistent": gaps_consistent,
        "note": "" if score >= 0.8 else "Execution quality degraded",
    }


def build_recommendation(status: str) -> str:
    """Human-readable recommendation string."""
    rec = RECOMMENDATIONS.get(status, "Unknown status")
    if status == "WARMUP":
        rec = rec.format(threshold=WARMUP_THRESHOLD)
    return rec


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def run_analysis() -> dict[str, Any]:
    """
    Run full drift analysis across all monitored strategies.
    Returns the complete status payload.
    """
    expectations = load_expectations()
    all_trades = load_trades()
    now = datetime.now(timezone.utc).isoformat()

    # Portfolio-level kill switch
    portfolio_scale = compute_portfolio_scale({})

    # Correlation spike detector
    corr_scale, avg_corr = compute_correlation_scale(all_trades)

    # Combined portfolio scale = DD scale * correlation scale
    combined_scale = portfolio_scale * corr_scale
    if combined_scale < 1.0:
        log.info(f"Portfolio scale: {combined_scale:.2f} (DD={portfolio_scale:.2f} × corr={corr_scale:.2f}, avg_corr={avg_corr:.2f})")

    strategies_output: dict[str, Any] = {}

    for strat in MONITORED_STRATEGIES:
        exp = expectations.get(strat)
        if not exp:
            log.warning("No expectations for %s — skipping", strat)
            continue

        window = filter_trades(all_trades, strat)
        metrics = compute_metrics(window, exp)
        metrics["strategy_code"] = strat  # needed for recovery logic
        status = classify(metrics)

        # Execution quality
        exec_info = compute_execution_score(all_trades, strat)

        # Prop pressure — soft curve from prop challenge tracker
        prop_mult = 1.0
        try:
            from services.prop_tracker import load_account, prop_pressure
            prop_acc = load_account()
            prop_mult = prop_pressure(prop_acc)
        except Exception:
            prop_mult = 1.0

        # Final weight = drift × portfolio_DD × correlation × execution × prop
        # With dominant risk override + soft floor anti-overcompression
        MIN_PORTFOLIO_SCALE = 0.25
        drift_weight = WEIGHT_MAP.get(status, 0.5)
        exec_score = exec_info["execution_score"]

        # Dominant risk override — these signals dominate, not blend
        if status == "KILL":
            final_weight = 0.0
        elif exec_score < 0.3:
            final_weight = drift_weight * 0.2
        else:
            # Normal blended: drift × portfolio × correlation × execution × prop
            blended = drift_weight * combined_scale * exec_score * prop_mult
            floor = MIN_PORTFOLIO_SCALE * drift_weight
            final_weight = max(blended, floor)

        # Warmup protection: disable correlation/execution penalties with < 30 trades total
        total_live_trades = sum(
            1 for t in all_trades
            if t.get("action") == "exit" and t.get("pnl_dollars", 0) != 0
        )
        if total_live_trades < 30:
            # In warmup phase — only use drift weight, skip noisy multipliers
            final_weight = drift_weight

        strategies_output[strat] = {
            "status": status,
            "live_trades": metrics["live_trades"],
            "live_win_rate": metrics["live_win_rate"],
            "live_mean_return": metrics["live_mean_return"],
            "live_total_pnl": metrics["live_total_pnl"],
            "live_max_dd": metrics["live_max_dd"],
            "z_score": metrics["z_score"],
            "dd_ratio": metrics["dd_ratio"],
            "freq_deviation": metrics["freq_deviation"],
            "wr_drop": metrics["wr_drop"],
            "consecutive_losses": metrics["consecutive_losses"],
            "recommendation": build_recommendation(status),
            "weight_multiplier": round(final_weight, 3),
            "weight_breakdown": {
                "drift": drift_weight,
                "portfolio_dd": portfolio_scale,
                "correlation": corr_scale,
                "execution": exec_info["execution_score"],
                "prop_pressure": prop_mult,
                "combined_scale": combined_scale,
                "blended": round(drift_weight * combined_scale * exec_score * prop_mult, 4),
                "final": round(final_weight, 4),
                "warmup_override": total_live_trades < 30,
            },
            "avg_correlation": round(avg_corr, 4),
            "execution_details": exec_info,
        }

        log.info(
            "%s → %s (trades=%d, z=%.2f, dd=%.2f, w=%.2f [drift=%.1f×port=%.1f×corr=%.1f×exec=%.2f])",
            strat, status, metrics["live_trades"], metrics["z_score"],
            metrics["dd_ratio"], final_weight,
            drift_weight, combined_scale, corr_scale, exec_score,
        )

    payload = {
        "timestamp": now,
        "portfolio_dd_scale": portfolio_scale,
        "correlation_scale": corr_scale,
        "avg_correlation": round(avg_corr, 4),
        "combined_scale": combined_scale,
        "strategies": strategies_output,
    }

    # Write outputs
    _atomic_write_json(STATUS_FILE, payload)
    log.info("Wrote drift_status.json")

    # Append to history (compact per-strategy summary)
    history_record = {
        "timestamp": now,
        "strategies": {
            name: {
                "status": s["status"],
                "weight": s["weight_multiplier"],
                "trades": s["live_trades"],
                "z_score": s["z_score"],
                "dd_ratio": s["dd_ratio"],
            }
            for name, s in strategies_output.items()
        },
    }
    _append_jsonl(HISTORY_FILE, history_record)
    log.info("Appended to drift_history.jsonl")

    return payload


# ---------------------------------------------------------------------------
# Report formatter
# ---------------------------------------------------------------------------

def format_report(payload: dict[str, Any]) -> str:
    """Generate a human-readable markdown report."""
    ts = payload["timestamp"]
    lines = [f"📊 Drift Monitor Report — {ts}", ""]

    actions_needed = []

    for strat in MONITORED_STRATEGIES:
        s = payload["strategies"].get(strat)
        if not s:
            lines.append(f"{strat}:")
            lines.append("  No expectations configured\n")
            continue

        emoji = STATUS_EMOJI.get(s["status"], "❓")
        n = s["live_trades"]

        lines.append(f"{strat}:")

        if n == 0:
            lines.append(f"  Status: {emoji} {s['status']} (0/{WARMUP_THRESHOLD} trades)")
            lines.append("  No trades yet")
        else:
            warmup_note = ""
            if s["status"] == "WARMUP":
                warmup_note = f" (warmup: {n}/{WARMUP_THRESHOLD} trades)"
            elif n < WARMUP_THRESHOLD:
                warmup_note = f" ({n}/{WARMUP_THRESHOLD} trades)"

            lines.append(f"  Status: {emoji} {s['status']}{warmup_note}")
            lines.append(
                f"  Z-Score: {s['z_score']:.2f} | "
                f"DD Ratio: {s['dd_ratio']:.2f}x | "
                f"Freq Dev: {s['freq_deviation']*100:.0f}%"
            )
            lines.append(
                f"  Live: {n} trades, {s['live_win_rate']*100:.0f}% WR, "
                f"${s['live_total_pnl']:+,.0f}"
            )

            # Load expectations for context
            expectations = load_expectations()
            exp = expectations.get(strat, {})
            lines.append(
                f"  Expected: {exp.get('expected_win_rate', 0)*100:.0f}% WR, "
                f"{exp.get('expected_max_dd_pct', 0):.0f}% max DD"
            )

            if s["consecutive_losses"] > 0:
                lines.append(f"  Consecutive losses: {s['consecutive_losses']}")

        lines.append("")

        if s and s["status"] in ("REDUCE", "KILL"):
            actions_needed.append(f"{strat}: {s['recommendation']}")

    lines.append("Actions Required: " + ("; ".join(actions_needed) if actions_needed else "None"))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Daemon loop
# ---------------------------------------------------------------------------

def daemon_loop() -> None:
    """Run analysis every DAEMON_INTERVAL_SEC until shutdown signal."""
    log.info(
        "Starting drift monitor daemon (interval=%ds, pid=%d)",
        DAEMON_INTERVAL_SEC,
        os.getpid(),
    )

    while not _shutdown:
        try:
            payload = run_analysis()
            # Quick summary to stdout
            for name, s in payload["strategies"].items():
                emoji = STATUS_EMOJI.get(s["status"], "?")
                print(
                    f"  {emoji} {name}: {s['status']} "
                    f"(w={s['weight_multiplier']}, trades={s['live_trades']})"
                )
        except Exception:
            log.exception("Analysis cycle failed — will retry next interval")

        # Sleep in small increments so we can catch shutdown signals
        for _ in range(DAEMON_INTERVAL_SEC):
            if _shutdown:
                break
            time.sleep(1)

    log.info("Daemon stopped")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Live Drift Monitor — detect strategy divergence from backtest expectations"
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run continuously, checking every 15 minutes",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print human-readable markdown report and exit",
    )
    args = parser.parse_args()

    # Ensure data dirs exist
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)

    if args.daemon:
        daemon_loop()
    else:
        payload = run_analysis()
        if args.report:
            print(format_report(payload))
        else:
            # Default: compact summary
            print(format_report(payload))


if __name__ == "__main__":
    main()


# ===========================================================================
# systemd service configuration
# ===========================================================================
# Save as: /etc/systemd/system/drift-monitor.service
#
# [Unit]
# Description=Trading Factory Drift Monitor
# After=network.target
# Wants=network.target
#
# [Service]
# Type=simple
# User=ochenryceo
# Group=ochenryceo
# WorkingDirectory=Path(__file__).resolve().parents[1]
# ExecStart=/usr/bin/python3 Path(__file__).resolve().parents[1]/services/drift_monitor.py --daemon
# Restart=on-failure
# RestartSec=30
# StandardOutput=journal
# StandardError=journal
# SyslogIdentifier=drift-monitor
# Environment=PYTHONUNBUFFERED=1
#
# # Resource limits
# MemoryMax=100M
# CPUQuota=10%
#
# [Install]
# WantedBy=multi-user.target
#
# --- Enable & start ---
# sudo systemctl daemon-reload
# sudo systemctl enable drift-monitor
# sudo systemctl start drift-monitor
# sudo journalctl -u drift-monitor -f
# ===========================================================================
