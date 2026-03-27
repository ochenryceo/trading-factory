#!/usr/bin/env python3
"""
🧠 THE BRAIN — Intelligence Flow Engine

Wires the 4 layers together with feedback loops.
Runs on Machine A as the central nervous system.

Command Flow:
  Henry → Apex → Strategist+Rebel → Scheduler → GPU Dispatcher → Darwin → Overseer → Vault

Feedback Loops:
  Loop 1 (Learning):  Darwin → Vault → Strategist → Scheduler
  Loop 2 (Failure):   Rejected → Vault → Rebel → Strategist
  Loop 3 (Resource):  Sentinel → Henry → Scheduler
"""

import json
import time
import signal
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any
from collections import Counter

PROJECT = Path(__file__).resolve().parents[1]
DATA = PROJECT / "data"

# ── Logging ────────────────────────────────────────────────────────────────
log = logging.getLogger("brain")
if not log.handlers:
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [🧠 BRAIN] %(message)s")
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    fh = logging.FileHandler(DATA / "brain.log")
    fh.setFormatter(fmt)
    log.addHandler(sh)
    log.addHandler(fh)
    log.propagate = False

# Lifecycle stage emojis (from cluster_lifecycle)
STAGES = {"BIRTH": "🌱", "GROWING": "📈", "PEAK": "🏆", "DECLINING": "📉", "DEAD": "💀", "REVIVING": "🔄"}


# ── Vault: Knowledge System ───────────────────────────────────────────────

class Vault:
    """
    NOT just storage. A knowledge system.
    
    Stores: all failures, all passes, cluster performance, patterns.
    Returns: "this pattern failed 73% of the time"
    """
    
    KNOWLEDGE_PATH = DATA / "vault_knowledge.json"
    
    @classmethod
    def load(cls) -> Dict:
        if cls.KNOWLEDGE_PATH.exists():
            with open(cls.KNOWLEDGE_PATH) as f:
                return json.load(f)
        return {
            "patterns": {},
            "cluster_performance": {},
            "strategy_outcomes": {"passed": 0, "failed": 0},
            "style_success_rates": {},
            "timeframe_success_rates": {},
            "asset_success_rates": {},
            "last_updated": None,
        }
    
    @classmethod
    def save(cls, knowledge: Dict):
        knowledge["last_updated"] = datetime.now(timezone.utc).isoformat()
        cls.KNOWLEDGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(cls.KNOWLEDGE_PATH, "w") as f:
            json.dump(knowledge, f, indent=2, default=str)
    
    @classmethod
    def record_outcome(cls, strategy: Dict, passed: bool):
        """Record a strategy outcome for learning."""
        k = cls.load()
        
        style = strategy.get("style", "unknown")
        tf = strategy.get("timeframe", "unknown")
        asset = strategy.get("asset", "unknown")
        
        # Overall
        if passed:
            k["strategy_outcomes"]["passed"] += 1
        else:
            k["strategy_outcomes"]["failed"] += 1
        
        # Per style
        if style not in k["style_success_rates"]:
            k["style_success_rates"][style] = {"tested": 0, "passed": 0}
        k["style_success_rates"][style]["tested"] += 1
        if passed:
            k["style_success_rates"][style]["passed"] += 1
        
        # Per timeframe
        if tf not in k["timeframe_success_rates"]:
            k["timeframe_success_rates"][tf] = {"tested": 0, "passed": 0}
        k["timeframe_success_rates"][tf]["tested"] += 1
        if passed:
            k["timeframe_success_rates"][tf]["passed"] += 1
        
        # Per asset
        if asset not in k["asset_success_rates"]:
            k["asset_success_rates"][asset] = {"tested": 0, "passed": 0}
        k["asset_success_rates"][asset]["tested"] += 1
        if passed:
            k["asset_success_rates"][asset]["passed"] += 1
        
        # Cluster
        cluster = f"{asset}/{tf}/{style}"
        if cluster not in k["cluster_performance"]:
            k["cluster_performance"][cluster] = {"tested": 0, "passed": 0, "best_sharpe": 0}
        k["cluster_performance"][cluster]["tested"] += 1
        if passed:
            k["cluster_performance"][cluster]["passed"] += 1
            sr = strategy.get("sharpe_ratio", 0)
            if sr > k["cluster_performance"][cluster]["best_sharpe"]:
                k["cluster_performance"][cluster]["best_sharpe"] = sr
        
        cls.save(k)
    
    @classmethod
    def query_pattern(cls, pattern: str) -> str:
        """Ask Vault about a pattern. Returns human-readable insight."""
        k = cls.load()
        
        # Check failure patterns
        fp_path = DATA / "failure_patterns.json"
        if fp_path.exists():
            with open(fp_path) as f:
                fp = json.load(f)
            patterns = fp.get("patterns", {})
            total = fp.get("total_failures", 1)
            if pattern in patterns:
                count = patterns[pattern]
                pct = count / total * 100
                return f"{pattern} has occurred {count} times ({pct:.0f}% of all failures)"
        
        return f"No data on pattern: {pattern}"
    
    @classmethod
    def get_best_clusters(cls, top_n: int = 5) -> List[Dict]:
        """Return the most promising clusters."""
        k = cls.load()
        clusters = []
        for key, data in k.get("cluster_performance", {}).items():
            tested = data.get("tested", 0)
            passed = data.get("passed", 0)
            if tested >= 5:
                rate = passed / tested
                clusters.append({
                    "cluster": key,
                    "tested": tested,
                    "passed": passed,
                    "pass_rate": round(rate, 3),
                    "best_sharpe": data.get("best_sharpe", 0),
                })
        clusters.sort(key=lambda x: x["pass_rate"], reverse=True)
        return clusters[:top_n]
    
    @classmethod
    def get_worst_clusters(cls, top_n: int = 5) -> List[Dict]:
        """Return the worst performing clusters (candidates for deprioritization)."""
        k = cls.load()
        clusters = []
        for key, data in k.get("cluster_performance", {}).items():
            tested = data.get("tested", 0)
            passed = data.get("passed", 0)
            if tested >= 10:
                rate = passed / tested
                clusters.append({
                    "cluster": key,
                    "tested": tested,
                    "passed": passed,
                    "pass_rate": round(rate, 3),
                })
        clusters.sort(key=lambda x: x["pass_rate"])
        return clusters[:top_n]


# ── Strategist: Cluster Intelligence ──────────────────────────────────────

class StrategistIntel:
    """
    Pattern detection + cluster intelligence.
    
    Tracks:
    - Best timeframe per asset
    - Best style per market
    - Saturated clusters
    - Emerging clusters
    """
    
    @staticmethod
    def analyze() -> Dict:
        """Full intelligence analysis with Style × Timeframe × Asset scoring."""
        k = Vault.load()
        
        analysis = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "best_per_asset": {},
            "best_per_timeframe": {},
            "saturated_clusters": [],
            "emerging_clusters": [],
            "recommendations": [],
            "edge_map": [],  # Style × Timeframe × Asset scores
            "revival_candidates": [],  # styles showing improvement
        }
        
        # Best timeframe per asset
        for asset in ["NQ", "GC", "CL"]:
            best_tf = None
            best_rate = 0
            for key, data in k.get("cluster_performance", {}).items():
                if key.startswith(f"{asset}/") and data.get("tested", 0) >= 5:
                    rate = data.get("passed", 0) / data.get("tested", 1)
                    if rate > best_rate:
                        best_rate = rate
                        best_tf = key.split("/")[1]
            if best_tf:
                analysis["best_per_asset"][asset] = {"timeframe": best_tf, "pass_rate": round(best_rate, 3)}
        
        # Saturated vs emerging
        for key, data in k.get("cluster_performance", {}).items():
            tested = data.get("tested", 0)
            passed = data.get("passed", 0)
            
            if tested >= 20 and (passed / max(tested, 1)) < 0.02:
                analysis["saturated_clusters"].append(key)
                analysis["recommendations"].append(f"REDUCE compute for {key} — saturated ({passed}/{tested} pass rate)")
            
            if tested < 10 and passed > 0:
                analysis["emerging_clusters"].append(key)
                analysis["recommendations"].append(f"INCREASE compute for {key} — emerging ({passed}/{tested}, needs exploration)")
        
        # ── Edge Map: Style × Timeframe × Asset scoring ──
        for key, data in k.get("cluster_performance", {}).items():
            parts = key.split("/")
            if len(parts) >= 3:
                tested = data.get("tested", 0)
                passed = data.get("passed", 0)
                best_sr = data.get("best_sharpe", 0)
                if tested >= 5:
                    rate = passed / tested
                    # Score: weighted combination of pass rate and best sharpe
                    score = round(rate * 0.6 + min(best_sr / 5, 1) * 0.4, 3)
                    analysis["edge_map"].append({
                        "cluster": key,
                        "asset": parts[0],
                        "timeframe": parts[1],
                        "style": parts[2],
                        "tested": tested,
                        "passed": passed,
                        "pass_rate": round(rate, 3),
                        "best_sharpe": best_sr,
                        "score": score,
                        "rating": "HIGH" if score > 0.5 else "MEDIUM" if score > 0.2 else "LOW",
                    })
        
        # Sort edge map by score
        analysis["edge_map"].sort(key=lambda x: -x["score"])
        
        # ── Cluster Decay Detection ──
        # Compare current scores vs previous cycle. If >30% drop, flag EDGE_DECAY.
        analysis["decay_alerts"] = []
        prev_path = DATA / "brain_edge_history.json"
        prev_scores = {}
        if prev_path.exists():
            try:
                with open(prev_path) as f:
                    prev_data = json.load(f)
                prev_scores = {e["cluster"]: e["score"] for e in prev_data.get("edge_map", [])}
            except:
                pass
        
        for entry in analysis["edge_map"]:
            cluster = entry["cluster"]
            current = entry["score"]
            prev = prev_scores.get(cluster, 0)
            
            if prev > 0.1 and current < prev * 0.7:
                drop_pct = round((1 - current / prev) * 100)
                analysis["decay_alerts"].append({
                    "cluster": cluster,
                    "prev_score": prev,
                    "current_score": current,
                    "drop_pct": drop_pct,
                    "alert": f"EDGE_DECAY: {cluster} dropped {drop_pct}% ({prev:.3f} → {current:.3f})",
                })
        
        # Save current scores as history for next cycle comparison
        try:
            with open(prev_path, "w") as f:
                json.dump({"edge_map": analysis["edge_map"], "timestamp": analysis["timestamp"]}, f, default=str)
        except:
            pass
        
        # ── Revival Trigger: check if weak styles are improving ──
        # Compare recent pass rate vs overall — if improving, flag for revival
        for key, data in k.get("cluster_performance", {}).items():
            parts = key.split("/")
            if len(parts) >= 3:
                style = parts[2]
                tested = data.get("tested", 0)
                passed = data.get("passed", 0)
                if tested >= 20 and passed / tested < 0.05:
                    # Currently weak — check if recent results are better
                    # (simple heuristic: if discoveries > 0, there's life)
                    if data.get("discoveries", 0) > 0:
                        analysis["revival_candidates"].append({
                            "cluster": key,
                            "style": style,
                            "tested": tested,
                            "passed": passed,
                            "note": "Shows signs of life — consider increasing compute",
                        })
        
        return analysis


# ── System Metrics ────────────────────────────────────────────────────────

class SystemMetrics:
    """
    Non-negotiable system metrics.
    
    Tracks:
    - Strategies/hour
    - Pass rate per agent
    - Compute per success
    - Cluster performance
    """
    
    METRICS_PATH = DATA / "system_metrics.json"
    
    @classmethod
    def calculate(cls) -> Dict:
        """Calculate current system metrics."""
        metrics = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "strategies_per_hour": 0,
            "pass_rate": 0,
            "agent_performance": {},
            "compute_efficiency": 0,
        }
        
        # Count from run log
        run_log = DATA / "continuous_run_log.jsonl"
        if not run_log.exists():
            return metrics
        
        total = 0
        passed = 0
        agent_stats = {}
        first_ts = None
        last_ts = None
        
        with open(run_log) as f:
            for line in f:
                try:
                    d = json.loads(line.strip())
                    total += 1
                    if d.get("passed_darwin"):
                        passed += 1
                    
                    agent = d.get("agent", "unknown")
                    if agent not in agent_stats:
                        agent_stats[agent] = {"tested": 0, "passed": 0}
                    agent_stats[agent]["tested"] += 1
                    if d.get("passed_darwin"):
                        agent_stats[agent]["passed"] += 1
                    
                    ts = d.get("timestamp", "")
                    if ts:
                        if first_ts is None or ts < first_ts:
                            first_ts = ts
                        if last_ts is None or ts > last_ts:
                            last_ts = ts
                except:
                    continue
        
        # Calculate rates
        if total > 0:
            metrics["pass_rate"] = round(passed / total, 4)
        
        if first_ts and last_ts:
            try:
                t1 = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
                t2 = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                hours = (t2 - t1).total_seconds() / 3600
                if hours > 0:
                    metrics["strategies_per_hour"] = round(total / hours)
            except:
                pass
        
        # Per-agent
        for agent, stats in agent_stats.items():
            rate = stats["passed"] / max(stats["tested"], 1)
            metrics["agent_performance"][agent] = {
                "tested": stats["tested"],
                "passed": stats["passed"],
                "pass_rate": round(rate, 4),
            }
        
        # Compute efficiency (passes per 1000 tests)
        if total > 0:
            metrics["compute_efficiency"] = round(passed / total * 1000, 1)
        
        metrics["total_tested"] = total
        metrics["total_passed"] = passed
        
        # Save
        cls.METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(cls.METRICS_PATH, "w") as f:
            json.dump(metrics, f, indent=2, default=str)
        
        return metrics


# ── Brain Loop (Main Intelligence Cycle) ──────────────────────────────────

def run_brain_cycle():
    """
    One cycle of the brain.
    
    1. Gather metrics (Sentinel role)
    2. Analyze clusters (Strategist role)
    3. Update knowledge (Vault role)
    4. Generate directives (Scheduler role)
    5. Log everything (Henry role)
    """
    log.info("━━━ BRAIN CYCLE START ━━━")
    
    # 1. System metrics
    metrics = SystemMetrics.calculate()
    log.info(f"📊 Metrics: {metrics.get('total_tested', 0):,} tested | "
             f"{metrics.get('total_passed', 0)} passed | "
             f"{metrics.get('strategies_per_hour', 0)}/hr | "
             f"efficiency: {metrics.get('compute_efficiency', 0)} per 1K")
    
    # 2. Cluster intelligence
    intel = StrategistIntel.analyze()
    if intel.get("best_per_asset"):
        for asset, data in intel["best_per_asset"].items():
            log.info(f"🧬 {asset} best: {data['timeframe']} ({data['pass_rate']:.0%} pass rate)")
    
    if intel.get("saturated_clusters"):
        log.info(f"⚠️ Saturated: {', '.join(intel['saturated_clusters'][:3])}")
    if intel.get("emerging_clusters"):
        log.info(f"🌱 Emerging: {', '.join(intel['emerging_clusters'][:3])}")
    
    # Edge map — top scoring clusters
    edge_map = intel.get("edge_map", [])
    if edge_map:
        log.info(f"🗺️ EDGE MAP (top 5):")
        for e in edge_map[:5]:
            log.info(f"   {e['rating']:6s} {e['cluster']:35s} score={e['score']:.3f} rate={e['pass_rate']:.0%} S={e['best_sharpe']:.2f}")
    
    # Revival candidates
    revivals = intel.get("revival_candidates", [])
    if revivals:
        log.info(f"🔄 REVIVAL CANDIDATES: {len(revivals)} styles showing improvement")
    
    # Decay alerts
    decays = intel.get("decay_alerts", [])
    if decays:
        log.info(f"🚨 EDGE DECAY DETECTED: {len(decays)} clusters declining")
        for d in decays[:3]:
            log.info(f"   ⚠️ {d['alert']}")
    
    # 3. Update Vault with run log data
    run_log = DATA / "continuous_run_log.jsonl"
    if run_log.exists():
        new_entries = 0
        with open(run_log) as f:
            for line in f:
                try:
                    d = json.loads(line.strip())
                    Vault.record_outcome(d, d.get("passed_darwin", False))
                    new_entries += 1
                except:
                    continue
        if new_entries > 0:
            log.info(f"💾 Vault updated with {new_entries} outcomes")
    
    # 4. Best/worst clusters
    best = Vault.get_best_clusters(3)
    worst = Vault.get_worst_clusters(3)
    
    if best:
        best_str = ", ".join(c["cluster"] + " (" + str(round(c["pass_rate"]*100)) + "%)" for c in best)
        log.info(f"🏆 Top clusters: {best_str}")
    if worst:
        worst_str = ", ".join(c["cluster"] + " (" + str(round(c["pass_rate"]*100)) + "%)" for c in worst)
        log.info(f"📉 Weak clusters: {worst_str}")
    
    # 5. Save intelligence analysis
    intel_path = DATA / "brain_intelligence.json"
    with open(intel_path, "w") as f:
        json.dump({
            "metrics": metrics,
            "intelligence": intel,
            "best_clusters": best,
            "worst_clusters": worst,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, f, indent=2, default=str)
    
    # 6. Cluster lifecycle tracking
    try:
        from services.cluster_lifecycle import get_tracker
        tracker = get_tracker()
        edge_map = intel.get("edge_map", [])
        if edge_map:
            tracker.record_snapshot(edge_map)
            lc_summary = tracker.get_summary()
            stage_counts = lc_summary.get("stage_counts", {})
            if stage_counts:
                stages_str = " | ".join(f"{STAGES.get(s,'?')} {s}: {c}" for s, c in stage_counts.items() if c > 0)
                log.info(f"🔄 LIFECYCLE: {stages_str}")
    except Exception as e:
        log.debug(f"Lifecycle tracking error: {e}")
    
    log.info("━━━ BRAIN CYCLE COMPLETE ━━━")
    
    return metrics, intel


# ── Brain Daemon ──────────────────────────────────────────────────────────

def main():
    """Run brain cycles every 5 minutes."""
    running = True
    
    def shutdown(signum, frame):
        nonlocal running
        running = False
    
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    
    log.info("🧠 BRAIN ONLINE — Machine A Super AI Brain activated")
    
    while running:
        try:
            run_brain_cycle()
        except Exception as e:
            log.error(f"Brain cycle error: {e}")
        
        # Sleep 5 minutes between cycles
        for _ in range(300):
            if not running:
                break
            time.sleep(1)
    
    log.info("🧠 BRAIN OFFLINE")


if __name__ == "__main__":
    main()
