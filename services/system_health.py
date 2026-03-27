#!/usr/bin/env python3
"""
System Health Snapshot — One-glance operational status.
Runs hourly via cron or on-demand. Outputs to health_snapshot.json + Discord.

Usage:
    python system_health.py           # generate snapshot, print to stdout
    python system_health.py --json    # output raw JSON only
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DATA = BASE / "data"

SNAPSHOT_FILE = DATA / "health_snapshot.json"
SNAPSHOT_HISTORY = DATA / "health_history.jsonl"


def _read_json(path, default=None):
    if not path.exists():
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _read_last_jsonl(path, n=5):
    if not path.exists():
        return []
    lines = []
    with open(path) as f:
        for line in f:
            lines.append(line.strip())
    return [json.loads(l) for l in lines[-n:] if l]


def generate_snapshot() -> dict:
    """Generate complete system health snapshot."""
    now = datetime.now(timezone.utc)

    # Discovery rate (last 5 generations)
    disc = _read_last_jsonl(DATA / "discovery_rate.jsonl", 5)
    discovery_rate = disc[-1].get("rate", 0) if disc else 0
    fitness_mean = disc[-1].get("mean_fitness", 0) if disc else 0
    fitness_std = disc[-1].get("fitness_std", 0) if disc else 0
    bias_influence = disc[-1].get("bias_influence", 0) if disc else 0
    dominant_style = disc[-1].get("dominant_style", "none") if disc else "none"
    style_dominance = disc[-1].get("style_dominance", 0) if disc else 0

    # Discovery trend
    if len(disc) >= 3:
        rates = [d.get("rate", 0) for d in disc]
        trend = "improving" if rates[-1] > rates[0] * 1.1 else "flat" if abs(rates[-1] - rates[0]) < 0.002 else "declining"
    else:
        trend = "warmup"

    # Backtester state
    bt_state = _read_json(DATA / "backtester_v2_state.json", {})
    total_tested = bt_state.get("total_strategies_tested", 0)
    total_passed = bt_state.get("total_passed", 0)
    current_gen = bt_state.get("generation", 0)

    # Control state
    ctrl = _read_json(DATA / "control_state.json", {})
    control_action = ctrl.get("last_action", "unknown")
    stagnation_counter = ctrl.get("stagnation_counter", 0)

    # Brain portfolio
    portfolio = _read_json(DATA / "brain_portfolio.json", {})
    active_strategies = portfolio.get("total_allocated", 0)
    portfolio_sharpe = portfolio.get("portfolio_expected_sharpe", 0)

    # Drift status
    drift = _read_json(DATA / "drift_status.json", {})
    drift_strategies = drift.get("strategies", {})
    kill_events = sum(1 for s in drift_strategies.values() if s.get("status") == "KILL")
    reduce_events = sum(1 for s in drift_strategies.values() if s.get("status") in ("REDUCE", "STRONG_REDUCE", "SEVERE"))
    portfolio_scale = min(s.get("portfolio_scale", 1.0) for s in drift_strategies.values()) if drift_strategies else 1.0

    # Near misses
    near_miss_count = 0
    nm_path = DATA / "near_misses.jsonl"
    if nm_path.exists():
        with open(nm_path) as f:
            near_miss_count = sum(1 for _ in f)

    # Lineage
    lineage = _read_json(DATA / "lineage_scores.json", {})
    top_family = None
    if lineage:
        best = max(lineage.items(), key=lambda x: x[1].get("best", 0))
        top_family = {"root": best[0], "best_fitness": best[1].get("best", 0), "descendants": best[1].get("count", 0)}

    # Param clusters
    clusters = _read_json(DATA / "param_clusters.json", {})
    n_style_clusters = len(clusters)

    # Paper trades
    trades = _read_json(DATA / "paper_trading/trades.json", [])
    paper_trades = len(trades) if isinstance(trades, list) else 0

    snapshot = {
        "timestamp": now.isoformat(),
        "generation": current_gen,
        "phase": "warmup" if current_gen < 200 else "learning" if current_gen < 500 else "mature",

        # Discovery
        "discovery_rate": round(discovery_rate, 6),
        "discovery_trend": trend,
        "total_tested": total_tested,
        "total_passed": total_passed,
        "lifetime_rate": round(total_passed / max(total_tested, 1), 6),

        # Fitness
        "fitness_mean": round(fitness_mean, 4),
        "fitness_std": round(fitness_std, 4),

        # Learning
        "bias_influence": round(bias_influence, 3),
        "control_action": control_action,
        "stagnation_counter": stagnation_counter,
        "dominant_style": dominant_style,
        "style_dominance": round(style_dominance, 3),
        "n_style_clusters": n_style_clusters,

        # Evolution
        "near_miss_count": near_miss_count,
        "top_family": top_family,
        "n_lineage_families": len(lineage),

        # Portfolio
        "active_strategies": active_strategies,
        "portfolio_sharpe": round(portfolio_sharpe, 2) if portfolio_sharpe else 0,
        "portfolio_scale": round(portfolio_scale, 3),
        "paper_trades": paper_trades,

        # Safety
        "kill_events_active": kill_events,
        "reduce_events_active": reduce_events,
    }

    # Write
    SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SNAPSHOT_FILE, "w") as f:
        json.dump(snapshot, f, indent=2)

    # Append history
    with open(SNAPSHOT_HISTORY, "a") as f:
        f.write(json.dumps(snapshot, separators=(",", ":")) + "\n")

    return snapshot


def format_report(s: dict) -> str:
    """Human-readable health report."""
    phase_emoji = {"warmup": "🌱", "learning": "📈", "mature": "🏛️"}.get(s["phase"], "❓")
    trend_emoji = {"improving": "📈", "flat": "➡️", "declining": "📉", "warmup": "🌱"}.get(s["discovery_trend"], "❓")

    lines = [
        f"🏥 System Health — {s['timestamp'][:16]} UTC",
        f"Phase: {phase_emoji} {s['phase'].upper()} (gen {s['generation']})",
        "",
        f"Discovery: {s['discovery_rate']:.3%} {trend_emoji} | Lifetime: {s['total_passed']}/{s['total_tested']}",
        f"Fitness: mean={s['fitness_mean']:.3f} std={s['fitness_std']:.3f}",
        f"Bias: {s['bias_influence']:.0%} | Control: {s['control_action']}",
        f"Styles: {s['n_style_clusters']} clusters, dominant={s['dominant_style']} ({s['style_dominance']:.0%})",
        "",
        f"Portfolio: {s['active_strategies']} strategies, sharpe={s['portfolio_sharpe']:.1f}, scale={s['portfolio_scale']:.0%}",
        f"Paper trades: {s['paper_trades']}",
        f"Near-misses: {s['near_miss_count']} | Families: {s['n_lineage_families']}",
        "",
        f"Safety: {s['kill_events_active']} kills, {s['reduce_events_active']} reduces",
    ]

    if s.get("top_family"):
        tf = s["top_family"]
        lines.append(f"Top family: {tf['root']} (fitness={tf['best_fitness']:.3f}, {tf['descendants']} descendants)")

    # Warnings
    warnings = []
    if s["fitness_std"] < 0.02 and s["generation"] > 50:
        warnings.append("⚠️ Over-convergence: fitness_std < 0.02")
    if s["bias_influence"] > 0.7:
        warnings.append("⚠️ Bias domination > 70%")
    if s["discovery_trend"] == "declining":
        warnings.append("⚠️ Discovery rate declining")
    if s["style_dominance"] > 0.7:
        warnings.append(f"⚠️ Style concentration: {s['dominant_style']} at {s['style_dominance']:.0%}")
    if s["kill_events_active"] > 0:
        warnings.append(f"🛑 {s['kill_events_active']} strategy kill(s) active")

    if warnings:
        lines.append("")
        lines.extend(warnings)
    else:
        lines.append("\n✅ All systems nominal")

    return "\n".join(lines)


# Hard safety rails — outer limits the control layer cannot exceed
HARD_RAILS = {
    "max_shock_freq_gens": 5,      # shock injection never more frequent than every 5 gens
    "min_random_ratio": 0.25,      # always at least 25% pure random
    "max_bias_influence": 0.85,    # if exceeded, force flatten
    "max_global_dd": 0.25,         # halt everything
}

# Intervention rules (for human reference)
INTERVENTION_RULES = """
ONLY intervene if:
1. Discovery rate declining for 20+ generations
2. Fitness mean collapses > 50% suddenly
3. One lineage dominates > 70% of all passes
4. Live trading diverges > 2 sigma from expected
5. System health shows > 2 concurrent warnings

Otherwise: HANDS OFF. Let the system learn.
"""


if __name__ == "__main__":
    snapshot = generate_snapshot()
    if "--json" in sys.argv:
        print(json.dumps(snapshot, indent=2))
    else:
        print(format_report(snapshot))
