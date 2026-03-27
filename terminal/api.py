"""
AI Trading System Terminal — API Backend
=========================================
READ-ONLY FastAPI server serving dashboard data from disk.
No writes. No mutations. No trading logic.

Run:
    uvicorn terminal.api:app --host 0.0.0.0 --port 8090
"""

import json
import os
import statistics
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PORT = 8090
HOST = "0.0.0.0"

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Trading Terminal API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def read_json(filename: str, default: Any = None) -> Any:
    """Read a JSON file from DATA_DIR. Returns default on any failure."""
    if default is None:
        default = {}
    try:
        path = DATA_DIR / filename
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def tail_jsonl(filename: str, n: int = 50) -> list[dict]:
    """
    Read the last N lines of a JSONL file efficiently.
    Uses a deque to avoid loading the entire file into memory.
    Returns parsed JSON objects; skips malformed lines.
    """
    path = DATA_DIR / filename
    if not path.exists():
        return []
    try:
        buf: deque[str] = deque(maxlen=n)
        with open(path, "r") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    buf.append(stripped)
        results = []
        for raw in buf:
            try:
                results.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        return results
    except OSError:
        return []


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/health")
def get_health() -> dict:
    """Full system health snapshot."""
    return read_json("health_snapshot.json")


@app.get("/api/system")
def get_system() -> dict:
    """Combined system overview: backtester + control + health."""
    return {
        "backtester_state": read_json("backtester_v2_state.json"),
        "control_state": read_json("control_state.json"),
        "health_snapshot": read_json("health_snapshot.json"),
    }


@app.get("/api/discovery")
def get_discovery() -> list:
    """Last 50 discovery rate entries (for charting)."""
    return tail_jsonl("discovery_rate.jsonl", n=50)


@app.get("/api/brain")
def get_brain() -> dict:
    """Brain portfolio and allocations."""
    return read_json("brain_portfolio.json")


@app.get("/api/drift")
def get_drift() -> dict:
    """Drift status for all strategies."""
    return read_json("drift_status.json")


@app.get("/api/prop")
def get_prop() -> dict:
    """Prop account state + history."""
    return {
        "status": read_json("prop_status.json"),
        "history": tail_jsonl("prop_history.jsonl", n=50),
    }


@app.get("/api/strategies")
def get_strategies() -> list:
    """Top strategies from the run log (last 100, sorted by fitness desc)."""
    entries = tail_jsonl("continuous_run_log.jsonl", n=100)
    # Sort by fitness if the field exists; highest first
    entries.sort(key=lambda e: e.get("fitness", 0), reverse=True)
    return entries


@app.get("/api/control")
def get_control() -> dict:
    """Control state + adaptive bias summary."""
    return {
        "control_state": read_json("control_state.json"),
        "adaptive_bias": read_json("adaptive_bias.json"),
    }


@app.get("/api/alerts")
def get_alerts() -> list:
    """Last 20 alerts from the alert queue."""
    return tail_jsonl("alert_queue.jsonl", n=20)


@app.get("/api/lineage")
def get_lineage() -> Any:
    """Top 20 lineage families."""
    data = read_json("lineage_scores.json", default=[])
    # If it's a dict with a list inside, extract it
    if isinstance(data, dict):
        # Try common keys
        for key in ("families", "scores", "lineage"):
            if key in data and isinstance(data[key], list):
                data = data[key]
                break
        else:
            # Return dict as-is if no list found
            return data
    if isinstance(data, list):
        return data[:20]
    return data


@app.get("/api/trades")
def get_trades() -> Any:
    """Paper trades."""
    return read_json("paper_trading/trades.json", default=[])


@app.get("/api/fitness-history")
def get_fitness_history() -> list:
    """
    Fitness mean/std over time derived from discovery_rate.jsonl.
    Groups entries by timestamp and computes rolling stats.
    """
    entries = tail_jsonl("discovery_rate.jsonl", n=50)
    results = []
    for entry in entries:
        ts = entry.get("timestamp") or entry.get("ts") or entry.get("time")
        fitness_vals = entry.get("fitness_values") or entry.get("fitnesses")
        if fitness_vals and isinstance(fitness_vals, list) and len(fitness_vals) > 0:
            mean = statistics.mean(fitness_vals)
            std = statistics.stdev(fitness_vals) if len(fitness_vals) > 1 else 0.0
            results.append({"timestamp": ts, "mean": round(mean, 6), "std": round(std, 6)})
        else:
            # Fall back to single fitness value if present
            f = entry.get("fitness") or entry.get("mean_fitness")
            if f is not None:
                results.append({
                    "timestamp": ts,
                    "mean": f,
                    "std": entry.get("std", entry.get("fitness_std", 0.0)),
                })
    return results


@app.get("/api/intelligence")
def get_intelligence() -> dict:
    """Decision intelligence layer — why the system hasn't won yet."""
    cs = read_json("control_state.json")
    bs = read_json("backtester_v2_state.json")
    es = read_json("expansion_state.json")
    ps = read_json("promotion_state.json")
    gs = read_json("production_gate_state.json")
    ds = read_json("diversity_stabilizer_state.json")

    stagnation = cs.get("stagnation_counter", 0)
    gen = bs.get("generation", 0)
    tested = bs.get("total_strategies_tested", 0)
    passed = bs.get("total_passed", 0)
    rates = cs.get("last_discovery_rates", [])

    # ── 1. BLOCKERS: Why no production strategy yet ──
    # Analyze recent run log for failure patterns
    recent = tail_jsonl("continuous_run_log.jsonl", n=200)
    failure_counts = {}
    for r in recent:
        reason = r.get("rejected_reason", "")
        if reason:
            failure_counts[reason] = failure_counts.get(reason, 0) + 1
        elif not r.get("passed_darwin", False):
            tier = r.get("darwin_tier", "rejected")
            if tier == "rejected":
                # Infer failure type
                tc = r.get("trade_count", 0)
                sh = r.get("sharpe_ratio", 0)
                wr = r.get("win_rate", 0)
                dd = r.get("max_drawdown", 0)
                if tc < 30:
                    failure_counts["low_trades"] = failure_counts.get("low_trades", 0) + 1
                elif sh < 0.5:
                    failure_counts["low_sharpe"] = failure_counts.get("low_sharpe", 0) + 1
                elif dd > 0.20:
                    failure_counts["high_drawdown"] = failure_counts.get("high_drawdown", 0) + 1
                elif wr < 0.40:
                    failure_counts["low_winrate"] = failure_counts.get("low_winrate", 0) + 1

    total_failures = sum(failure_counts.values()) or 1
    blockers = sorted(
        [{"reason": k, "count": v, "pct": round(v / total_failures * 100, 1)}
         for k, v in failure_counts.items()],
        key=lambda x: x["count"], reverse=True,
    )[:5]

    if stagnation < 500:
        primary_constraint = "Search space exhausted — awaiting expansion"
    elif not ps.get("promoted"):
        primary_constraint = "No surviving lineage found yet"
    elif not gs.get("approved"):
        primary_constraint = "No strategy passes Production Gate"
    else:
        primary_constraint = "Strategy approved — awaiting paper trading"

    # ── 2. EDGE PRESSURE ──
    discovery_dead = len(rates) >= 10 and all(r == 0 for r in rates[-10:])
    pressure_signals = []
    if stagnation > 300:
        pressure_signals.append(f"Stagnation: {stagnation}/500")
    if discovery_dead:
        pressure_signals.append("Discovery rate: 0% (10 consecutive windows)")
    div_state = ds.get("last_state", "")
    if "weak" in div_state.lower():
        pressure_signals.append(f"Diversity: {div_state}")
    dom = ds.get("consecutive_dominant", 0)
    if dom > 50:
        pressure_signals.append(f"Style dominance: {dom} consecutive gens")

    if stagnation >= 400:
        pressure_level = "CRITICAL"
        pressure_color = "red"
    elif stagnation >= 300:
        pressure_level = "HIGH"
        pressure_color = "orange"
    elif stagnation >= 150:
        pressure_level = "MODERATE"
        pressure_color = "yellow"
    else:
        pressure_level = "LOW"
        pressure_color = "green"

    # ── 3. EXPECTATION VS ACTUAL ──
    expectations = []
    if stagnation < 500:
        expectations.append({
            "metric": "Discovery rate",
            "expected": "0.0%",
            "actual": f"{rates[-1]*100:.1f}%" if rates else "N/A",
            "match": rates and rates[-1] == 0,
        })
        expectations.append({
            "metric": "Phase",
            "expected": "Stagnation",
            "actual": "Stagnation" if discovery_dead else "Exploring",
            "match": discovery_dead,
        })
        expectations.append({
            "metric": "Production candidates",
            "expected": "0",
            "actual": str(len(gs.get("approved", {}))),
            "match": len(gs.get("approved", {})) == 0,
        })
    else:
        expectations.append({
            "metric": "Expansion",
            "expected": "Active",
            "actual": "Active" if es.get("active") else "Inactive",
            "match": es.get("active", False),
        })

    all_match = all(e["match"] for e in expectations)

    # ── 4. ANOMALY DETECTION ──
    anomalies = []
    # Check for impossible results in recent log
    for r in recent[-50:]:
        if r.get("win_rate", 0) >= 0.98 and r.get("trade_count", 0) >= 50:
            anomalies.append({"type": "impossible_winrate", "severity": "warning",
                              "detail": f"{r.get('strategy_code','?')}: WR={r.get('win_rate',0):.0%} with {r.get('trade_count',0)} trades"})
        if r.get("sharpe_ratio", 0) > 8:
            anomalies.append({"type": "extreme_sharpe", "severity": "warning",
                              "detail": f"{r.get('strategy_code','?')}: Sharpe={r.get('sharpe_ratio',0):.1f}"})
    # Check for backtester state staleness
    try:
        state_age = os.path.getmtime(str(DATA_DIR / "backtester_v2_state.json"))
        import time
        if time.time() - state_age > 600:
            anomalies.append({"type": "stale_state", "severity": "critical",
                              "detail": "Backtester state not updated in 10+ minutes"})
    except Exception:
        pass

    # ── 5. SYSTEM INTENT ──
    if stagnation < 500:
        intent = {
            "goal": "Break stagnation via expansion",
            "strategy": "Maintain exploration pressure, exhaust current space",
            "next_objective": "Trigger expansion at stagnation ≥ 500",
        }
    elif not ps.get("promoted"):
        intent = {
            "goal": "Discover surviving lineage",
            "strategy": "Explore new dimensions, monitor lineage emergence",
            "next_objective": "Achieve STRONG signal (2+ surviving lineages, cross-style)",
        }
    elif not gs.get("approved"):
        intent = {
            "goal": "Pass Production Gate",
            "strategy": "Focused refinement of promoted lineage",
            "next_objective": "Strategy passes all 10 validation checks",
        }
    else:
        intent = {
            "goal": "Validate in paper trading",
            "strategy": "30-day live observation",
            "next_objective": "GO/NO-GO for real capital",
        }

    # ── 6. FAILURE MODE ──
    if stagnation < 500 and discovery_dead:
        failure_mode = {
            "mode": "SEARCH SPACE EXHAUSTION",
            "type": "Structural plateau",
            "severity": "Expected",
            "explanation": "System has mapped all reachable parameter combinations. This is the designed pressure that triggers expansion.",
        }
    elif stagnation >= 500 and not ps.get("promoted"):
        failure_mode = {
            "mode": "EXPANSION DISCOVERY",
            "type": "New space exploration",
            "severity": "Normal",
            "explanation": "System exploring expanded dimensions. Lineage emergence takes 50-150 gens.",
        }
    else:
        failure_mode = {
            "mode": "NONE",
            "type": "Nominal",
            "severity": "N/A",
            "explanation": "System operating within expected parameters.",
        }

    return {
        "blockers": {"primary_constraint": primary_constraint, "breakdown": blockers},
        "edge_pressure": {"level": pressure_level, "color": pressure_color, "signals": pressure_signals},
        "expectation_match": {"expectations": expectations, "all_match": all_match},
        "anomalies": anomalies,
        "intent": intent,
        "failure_mode": failure_mode,
    }


@app.get("/api/near-misses")
def get_near_misses() -> dict:
    """Near-miss strategies: count + top 10."""
    entries = tail_jsonl("near_misses.jsonl", n=100)
    return {
        "count": len(entries),
        "top": entries[-10:] if len(entries) > 10 else entries,
    }


@app.get("/api/param-clusters")
def get_param_clusters() -> Any:
    """Parameter clusters."""
    return read_json("param_clusters.json")


@app.get("/api/health-history")
def get_health_history() -> list:
    """Last 50 health history entries (for charts)."""
    return tail_jsonl("health_history.jsonl", n=50)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("terminal.api:app", host=HOST, port=PORT, log_level="info")


# ===========================================================================
# systemd service config
# ===========================================================================
#
# [Unit]
# Description=Trading Terminal API
# After=network.target
#
# [Service]
# Type=simple
# User=ochenryceo
# WorkingDirectory=Path(__file__).resolve().parents[1]
# ExecStart=/usr/bin/env uvicorn terminal.api:app --host 0.0.0.0 --port 8090
# Restart=on-failure
# RestartSec=5
# StandardOutput=journal
# StandardError=journal
# Environment=PYTHONUNBUFFERED=1
#
# [Install]
# WantedBy=multi-user.target
# ===========================================================================
