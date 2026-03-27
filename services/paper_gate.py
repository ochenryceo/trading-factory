"""
Paper Trading Gate — Shadow Execution Qualification
=====================================================
Lower bar than Production Gate. Strategies that pass here go to paper trading
for live validation. They do NOT get real capital.

Paper Gate criteria:
  - Fitness ≥ 0.80
  - Sharpe ≥ 1.8
  - Trades ≥ 80
  - MC worst DD ≤ 20%
  - WF mean sharpe ≥ 1.5
  - Max drawdown ≤ 15%
  - Win rate ≥ 50%

Pipeline:
  Persistence → [PAPER GATE] → Paper Trading Pool
  Persistence → [PRODUCTION GATE] → Live Capital (unchanged, ≥ 0.90)

Author: Henry (autonomous build)
Date: 2026-03-26
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("paper_gate")

BASE_DIR = Path("Path(__file__).resolve().parents[1]")
PAPER_POOL_FILE = BASE_DIR / "data" / "paper_trading_pool.json"
PAPER_GATE_LOG = BASE_DIR / "data" / "paper_gate_log.jsonl"

# ─── Paper Gate Thresholds ──────────────────────────────────────────────

PAPER_MIN_FITNESS = 0.80
PAPER_MIN_SHARPE = 1.8
PAPER_MIN_TRADES = 80
PAPER_MAX_MC_DD = 0.20
PAPER_MIN_WF_SHARPE = 1.5
PAPER_MAX_DD = 0.15
PAPER_MIN_WR = 0.50


def evaluate_paper(artifact: dict) -> dict:
    """
    Run paper trading gate on a candidate artifact.
    
    Args:
        artifact: Full candidate artifact from candidate_store
    
    Returns:
        {status: PAPER_APPROVED|PAPER_REJECTED, checks: {...}, reasons: [...]}
    """
    code = artifact["strategy_code"]
    perf = artifact["performance"]
    mc = artifact["monte_carlo"]
    wf = artifact["walk_forward"]
    fitness = artifact["fitness"]
    
    checks = {}
    failures = []
    
    # 1. Fitness
    fitness_ok = fitness >= PAPER_MIN_FITNESS
    checks["fitness"] = {"value": round(fitness, 4), "threshold": PAPER_MIN_FITNESS, "passed": fitness_ok}
    if not fitness_ok:
        failures.append(f"fitness {fitness:.3f} < {PAPER_MIN_FITNESS}")
    
    # 2. Sharpe
    sharpe = perf.get("sharpe_ratio", 0)
    sharpe_ok = sharpe >= PAPER_MIN_SHARPE
    checks["sharpe"] = {"value": round(sharpe, 4), "threshold": PAPER_MIN_SHARPE, "passed": sharpe_ok}
    if not sharpe_ok:
        failures.append(f"sharpe {sharpe:.2f} < {PAPER_MIN_SHARPE}")
    
    # 3. Trade count
    trades = perf.get("trade_count", 0)
    trades_ok = trades >= PAPER_MIN_TRADES
    checks["trade_count"] = {"value": trades, "threshold": PAPER_MIN_TRADES, "passed": trades_ok}
    if not trades_ok:
        failures.append(f"trades {trades} < {PAPER_MIN_TRADES}")
    
    # 4. MC worst DD
    mc_dd = abs(mc.get("mc_worst_dd", 1.0))
    mc_ok = mc_dd <= PAPER_MAX_MC_DD
    checks["mc_worst_dd"] = {"value": round(mc_dd, 4), "threshold": PAPER_MAX_MC_DD, "passed": mc_ok}
    if not mc_ok:
        failures.append(f"mc_worst_dd {mc_dd:.2%} > {PAPER_MAX_MC_DD:.0%}")
    
    # 5. WF mean sharpe
    wf_sharpe = wf.get("wf_mean_sharpe", 0)
    wf_ok = wf_sharpe >= PAPER_MIN_WF_SHARPE
    checks["wf_sharpe"] = {"value": round(wf_sharpe, 4), "threshold": PAPER_MIN_WF_SHARPE, "passed": wf_ok}
    if not wf_ok:
        failures.append(f"wf_sharpe {wf_sharpe:.2f} < {PAPER_MIN_WF_SHARPE}")
    
    # 6. Max drawdown
    dd = perf.get("max_drawdown", 1.0)
    dd_ok = dd <= PAPER_MAX_DD
    checks["max_drawdown"] = {"value": round(dd, 4), "threshold": PAPER_MAX_DD, "passed": dd_ok}
    if not dd_ok:
        failures.append(f"max_dd {dd:.2%} > {PAPER_MAX_DD:.0%}")
    
    # 7. Win rate
    wr = perf.get("win_rate", 0)
    wr_ok = wr >= PAPER_MIN_WR
    checks["win_rate"] = {"value": round(wr, 4), "threshold": PAPER_MIN_WR, "passed": wr_ok}
    if not wr_ok:
        failures.append(f"win_rate {wr:.1%} < {PAPER_MIN_WR:.0%}")
    
    # Verdict
    all_passed = all(c["passed"] for c in checks.values())
    status = "PAPER_APPROVED" if all_passed else "PAPER_REJECTED"
    
    result = {
        "strategy_code": code,
        "status": status,
        "checks": checks,
        "failure_reasons": failures,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fitness": fitness,
        "style": artifact["style"],
        "asset": artifact["asset"],
        "timeframe": artifact["timeframe"],
    }
    
    # Log
    _log_result(result)
    
    if status == "PAPER_APPROVED":
        _add_to_pool(artifact, result)
        log.info(f"📄 PAPER APPROVED: {code} (fitness={fitness:.3f}, sharpe={sharpe:.2f}, {trades} trades)")
        try:
            from services.discord_paper_monitor import alert_paper_gate_approved
            alert_paper_gate_approved(code, fitness, sharpe, trades)
        except Exception:
            pass
    
    return result


def _log_result(result: dict):
    """Append to gate log."""
    PAPER_GATE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(PAPER_GATE_LOG, "a") as f:
        f.write(json.dumps(result, separators=(",", ":"), default=str) + "\n")


def _add_to_pool(artifact: dict, gate_result: dict):
    """Add approved strategy to paper trading pool."""
    pool = load_pool()
    
    entry = {
        "strategy_code": artifact["strategy_code"],
        "style": artifact["style"],
        "asset": artifact["asset"],
        "timeframe": artifact["timeframe"],
        "parameters": artifact["parameters"],
        "fitness": artifact["fitness"],
        "sharpe": artifact["performance"]["sharpe_ratio"],
        "max_dd": artifact["performance"]["max_drawdown"],
        "win_rate": artifact["performance"]["win_rate"],
        "trade_count": artifact["performance"]["trade_count"],
        "wf_sharpe": artifact["walk_forward"]["wf_mean_sharpe"],
        "mc_worst_dd": artifact["monte_carlo"]["mc_worst_dd"],
        "added_at": datetime.now(timezone.utc).isoformat(),
        "generation": artifact.get("generation", 0),
        "status": "active",
        "paper_trades": 0,
        "paper_pnl": 0.0,
    }
    
    # Dedup by strategy code
    pool = [p for p in pool if p["strategy_code"] != entry["strategy_code"]]
    pool.append(entry)
    
    with open(PAPER_POOL_FILE, "w") as f:
        json.dump(pool, f, indent=2, default=str)


def load_pool() -> list:
    """Load current paper trading pool."""
    if not PAPER_POOL_FILE.exists():
        return []
    try:
        return json.load(open(PAPER_POOL_FILE))
    except Exception:
        return []


def run_all_candidates():
    """Run paper gate on all persisted candidates."""
    from services.candidate_store import list_candidates, load_candidate
    
    candidates = list_candidates()
    results = []
    
    for c in candidates:
        artifact = load_candidate(c["strategy_code"])
        if artifact:
            result = evaluate_paper(artifact)
            results.append(result)
    
    return results


if __name__ == "__main__":
    import sys
    
    results = run_all_candidates()
    
    approved = [r for r in results if r["status"] == "PAPER_APPROVED"]
    rejected = [r for r in results if r["status"] == "PAPER_REJECTED"]
    
    print(f"\nPaper Gate Results:")
    print(f"  📄 Approved: {len(approved)}")
    print(f"  ❌ Rejected: {len(rejected)}")
    
    for r in results:
        icon = "📄" if r["status"] == "PAPER_APPROVED" else "❌"
        print(f"\n  {icon} {r['strategy_code']} — {r['status']}")
        for name, check in r["checks"].items():
            ci = "✅" if check["passed"] else "❌"
            print(f"    {ci} {name}: {check['value']} (need {'≥' if name != 'mc_worst_dd' and name != 'max_drawdown' else '≤'} {check['threshold']})")
