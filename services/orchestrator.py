#!/usr/bin/env python3
"""
Orchestration Layer — Distributed Quantitative Trading System

Manages task allocation across CPU, RAM, and GPU resources.
Maximizes throughput, stability, and strategy discovery quality.

Machine A (Control): orchestration, API, monitoring
Machine B (Compute): strategy generation, backtesting, AI inference
"""

import json
import time
import logging
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from collections import Counter

log = logging.getLogger("orchestrator")

PROJECT = Path(__file__).resolve().parents[1]
CLUSTER_STATE_PATH = PROJECT / "data" / "cluster_state.json"
ORCHESTRATOR_LOG_PATH = PROJECT / "data" / "orchestrator.log"

MACHINE_B = "os.getenv("MACHINE_B_IP", "localhost")"
SSH_KEY = os.path.expanduser("~/.ssh/id_ed25519")
SSH = f"ssh -i {SSH_KEY} -o StrictHostKeyChecking=no -o ConnectTimeout=5 ochenryceo@{MACHINE_B}"

# ── Cluster Definitions ────────────────────────────────────────────────────

CLUSTERS = {}
for asset in ["NQ", "GC", "CL"]:
    for tf in ["5m", "15m", "1h", "4h", "daily"]:
        for style in ["momentum_breakout", "mean_reversion", "trend_following", "scalping", "volume_orderflow"]:
            key = f"{asset}/{tf}/{style}"
            CLUSTERS[key] = {
                "asset": asset, "timeframe": tf, "style": style,
                "tested": 0, "passed": 0, "best_sharpe": 0,
                "priority": "normal",  # high / normal / low / saturated
                "last_discovery": None,
            }


# ── Early Termination ──────────────────────────────────────────────────────

class EarlyTerminator:
    """
    Kill weak strategies fast to conserve compute.
    
    After initial N trades, check:
    - Sharpe < 0 → kill (negative expectancy)
    - Win rate < 25% → kill (not viable)
    - Max DD > 20% → kill (too risky)
    - Expectancy < 0 → kill (losing money)
    """
    
    EARLY_CHECK_TRADES = 10  # Check after this many trades
    
    @staticmethod
    def should_terminate(partial_result: Dict) -> bool:
        """Returns True if strategy should be killed early."""
        trades = partial_result.get("trade_count", 0)
        if trades < EarlyTerminator.EARLY_CHECK_TRADES:
            return False
        
        # Hard kills
        if partial_result.get("sharpe_ratio", 0) < -0.5:
            return True
        if partial_result.get("win_rate", 0) < 0.25:
            return True
        if partial_result.get("max_drawdown", 1) > 0.20:
            return True
        if partial_result.get("expectancy", 0) < -0.005:
            return True
        
        return False
    
    @staticmethod
    def reason(partial_result: Dict) -> str:
        if partial_result.get("sharpe_ratio", 0) < -0.5:
            return "negative_sharpe"
        if partial_result.get("win_rate", 0) < 0.25:
            return "low_win_rate"
        if partial_result.get("max_drawdown", 1) > 0.20:
            return "high_drawdown"
        if partial_result.get("expectancy", 0) < -0.005:
            return "negative_expectancy"
        return "unknown"


# ── Cluster-Aware Scheduling ──────────────────────────────────────────────

class ClusterScheduler:
    """
    Allocate compute based on cluster performance.
    
    - Underexplored clusters → more GPU time
    - Promising clusters → more GPU time
    - Saturated/redundant clusters → less GPU time
    """
    
    def __init__(self):
        self.state = self._load_state()
    
    def _load_state(self) -> Dict:
        if CLUSTER_STATE_PATH.exists():
            try:
                with open(CLUSTER_STATE_PATH) as f:
                    return json.load(f)
            except:
                pass
        return {"clusters": {}, "last_updated": None}
    
    def save_state(self):
        self.state["last_updated"] = datetime.now(timezone.utc).isoformat()
        CLUSTER_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CLUSTER_STATE_PATH, "w") as f:
            json.dump(self.state, f, indent=2, default=str)
    
    def record_result(self, asset: str, timeframe: str, style: str, passed: bool, sharpe: float = 0):
        """Record a backtest result for cluster tracking."""
        key = f"{asset}/{timeframe}/{style}"
        if key not in self.state.get("clusters", {}):
            self.state.setdefault("clusters", {})[key] = {
                "tested": 0, "passed": 0, "best_sharpe": 0,
                "priority": "normal", "discoveries": 0,
            }
        
        cluster = self.state["clusters"][key]
        cluster["tested"] += 1
        if passed:
            cluster["passed"] += 1
            cluster["discoveries"] += 1
            if sharpe > cluster.get("best_sharpe", 0):
                cluster["best_sharpe"] = sharpe
    
    def get_cluster_weights(self) -> Dict[str, float]:
        """
        Return weight multipliers for each cluster.
        Higher weight = more compute allocated.
        """
        weights = {}
        clusters = self.state.get("clusters", {})
        
        for key, data in clusters.items():
            tested = data.get("tested", 0)
            passed = data.get("passed", 0)
            best_sharpe = data.get("best_sharpe", 0)
            
            if tested == 0:
                # Underexplored → high priority
                weights[key] = 2.0
            elif tested < 20:
                # Still exploring
                weights[key] = 1.5
            else:
                pass_rate = passed / tested
                if pass_rate > 0.15 and best_sharpe > 1.0:
                    # Promising → high priority
                    weights[key] = 1.8
                elif pass_rate > 0.05:
                    # Normal
                    weights[key] = 1.0
                elif pass_rate > 0.01:
                    # Low yield
                    weights[key] = 0.5
                else:
                    # Saturated / no results → deprioritize
                    weights[key] = 0.2
        
        return weights
    
    def get_priority_timeframes(self, asset: str) -> List[str]:
        """Get timeframes sorted by priority for an asset."""
        weights = self.get_cluster_weights()
        tf_weights = {}
        
        for key, weight in weights.items():
            parts = key.split("/")
            if len(parts) >= 2 and parts[0] == asset:
                tf = parts[1]
                tf_weights[tf] = tf_weights.get(tf, 0) + weight
        
        # Sort by weight descending
        sorted_tfs = sorted(tf_weights.items(), key=lambda x: -x[1])
        return [tf for tf, _ in sorted_tfs]
    
    def get_summary(self) -> Dict:
        """Get cluster performance summary."""
        clusters = self.state.get("clusters", {})
        
        # Aggregate by timeframe
        by_tf = {}
        by_asset = {}
        by_style = {}
        
        for key, data in clusters.items():
            parts = key.split("/")
            if len(parts) >= 3:
                asset, tf, style = parts[0], parts[1], parts[2]
                
                for agg, k in [(by_tf, tf), (by_asset, asset), (by_style, style)]:
                    if k not in agg:
                        agg[k] = {"tested": 0, "passed": 0}
                    agg[k]["tested"] += data.get("tested", 0)
                    agg[k]["passed"] += data.get("passed", 0)
        
        return {
            "total_clusters": len(clusters),
            "by_timeframe": by_tf,
            "by_asset": by_asset,
            "by_style": by_style,
        }


# ── Resource Monitor ───────────────────────────────────────────────────────

class ResourceMonitor:
    """Monitor CPU, RAM, GPU across both machines."""
    
    @staticmethod
    def get_machine_a() -> Dict:
        """Get Machine A resource status."""
        try:
            import psutil
            return {
                "cpu_percent": psutil.cpu_percent(interval=1),
                "ram_percent": psutil.virtual_memory().percent,
                "ram_available_gb": psutil.virtual_memory().available / (1024**3),
            }
        except ImportError:
            return {"cpu_percent": 0, "ram_percent": 0, "ram_available_gb": 0}
    
    @staticmethod
    def get_machine_b() -> Dict:
        """Get Machine B resource status via SSH."""
        try:
            result = subprocess.run(
                [SSH.split()[0]] + SSH.split()[1:] + [
                    "python3 -c \"import json; "
                    "import subprocess; "
                    "gpu = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu', '--format=csv,noheader,nounits'], capture_output=True, text=True).stdout.strip().split(', '); "
                    "print(json.dumps({'gpu_util': int(gpu[0]), 'gpu_mem_used': int(gpu[1]), 'gpu_mem_total': int(gpu[2]), 'gpu_temp': int(gpu[3])}))\""
                ],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return json.loads(result.stdout.strip())
        except:
            pass
        return {"gpu_util": 0, "gpu_mem_used": 0, "gpu_mem_total": 0, "gpu_temp": 0}
    
    @staticmethod
    def should_throttle() -> bool:
        """Check if we need to reduce compute load."""
        b = ResourceMonitor.get_machine_b()
        if b.get("gpu_temp", 0) > 80:
            return True  # GPU overheating
        if b.get("gpu_util", 0) > 95:
            return True  # GPU maxed
        return False


# ── Orchestrator Core ──────────────────────────────────────────────────────

class Orchestrator:
    """
    Central orchestration layer.
    
    Manages:
    - Task allocation across CPU/RAM/GPU
    - Cluster-aware scheduling
    - Early termination
    - Resource monitoring
    - Agent coordination
    """
    
    def __init__(self):
        self.scheduler = ClusterScheduler()
        self.terminator = EarlyTerminator()
        self.monitor = ResourceMonitor()
    
    def get_agent_directive(self, agent_name: str, asset: str) -> Dict:
        """
        Generate a directive for an agent based on current cluster state.
        Returns prioritized timeframes and styles to focus on.
        """
        priority_tfs = self.scheduler.get_priority_timeframes(asset)
        weights = self.scheduler.get_cluster_weights()
        
        # Build style priorities for this asset
        style_weights = {}
        for key, weight in weights.items():
            parts = key.split("/")
            if len(parts) >= 3 and parts[0] == asset:
                style = parts[2]
                style_weights[style] = style_weights.get(style, 0) + weight
        
        sorted_styles = sorted(style_weights.items(), key=lambda x: -x[1])
        
        return {
            "agent": agent_name,
            "asset": asset,
            "priority_timeframes": priority_tfs[:3],  # Top 3
            "priority_styles": [s for s, _ in sorted_styles[:3]],
            "should_throttle": self.monitor.should_throttle(),
        }
    
    def record_and_evaluate(self, result: Dict) -> Dict:
        """
        Record a backtest result and return orchestrator decision.
        
        Returns:
        - continue: True/False (early termination check)
        - priority_shift: whether to adjust cluster priority
        """
        asset = result.get("asset", "")
        tf = result.get("timeframe", "")
        style = result.get("style", "")
        passed = result.get("passed_darwin", False)
        sharpe = result.get("sharpe_ratio", 0)
        
        # Record for cluster tracking
        self.scheduler.record_result(asset, tf, style, passed, sharpe)
        
        # Early termination check
        should_kill = self.terminator.should_terminate(result)
        
        return {
            "continue": not should_kill,
            "kill_reason": self.terminator.reason(result) if should_kill else None,
            "cluster_key": f"{asset}/{tf}/{style}",
        }
    
    def get_status(self) -> Dict:
        """Full orchestrator status report."""
        summary = self.scheduler.get_summary()
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "clusters": summary,
            "weights": self.scheduler.get_cluster_weights(),
            "throttle": self.monitor.should_throttle(),
        }
    
    def save(self):
        self.scheduler.save_state()


# ── Singleton ──────────────────────────────────────────────────────────────
_orchestrator = None

def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator
