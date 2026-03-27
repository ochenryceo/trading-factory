#!/usr/bin/env python3
"""
Cluster Lifecycle Tracker — Birth → Growth → Peak → Decay

Tracks every cluster's lifecycle stage over time.
Prevents chasing dead edges and missing new ones.

Output per cluster:
  CL/5m/volume_orderflow → rising (3 cycles) → peak (5 cycles) → decaying

Owner: Strategist + Sentinel
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List

log = logging.getLogger("cluster_lifecycle")

PROJECT = Path(__file__).resolve().parents[1]
DATA = PROJECT / "data"
LIFECYCLE_PATH = DATA / "cluster_lifecycle.json"
HISTORY_PATH = DATA / "cluster_score_history.json"

# Lifecycle stages
STAGES = {
    "BIRTH": "🌱",      # first seen, < 5 tests
    "GROWING": "📈",    # score increasing over 2+ cycles
    "PEAK": "🏆",       # score stable at high level
    "DECLINING": "📉",  # score dropping
    "DEAD": "💀",       # score near zero, many tests
    "REVIVING": "🔄",   # was dead/declining, now improving
}


class ClusterLifecycle:
    
    def __init__(self):
        self.history = self._load_history()
        self.lifecycle = self._load_lifecycle()
    
    def _load_history(self) -> Dict:
        if HISTORY_PATH.exists():
            try:
                with open(HISTORY_PATH) as f:
                    return json.load(f)
            except:
                pass
        return {"snapshots": [], "max_snapshots": 50}
    
    def _load_lifecycle(self) -> Dict:
        if LIFECYCLE_PATH.exists():
            try:
                with open(LIFECYCLE_PATH) as f:
                    return json.load(f)
            except:
                pass
        return {"clusters": {}, "last_updated": None}
    
    def record_snapshot(self, edge_map: List[Dict]):
        """Record current edge map as a snapshot for lifecycle tracking."""
        snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scores": {e["cluster"]: e["score"] for e in edge_map},
        }
        self.history["snapshots"].append(snapshot)
        
        # Keep last N snapshots
        max_s = self.history.get("max_snapshots", 50)
        if len(self.history["snapshots"]) > max_s:
            self.history["snapshots"] = self.history["snapshots"][-max_s:]
        
        self._save_history()
        self._update_lifecycle(edge_map)
    
    def _update_lifecycle(self, edge_map: List[Dict]):
        """Update lifecycle stage for each cluster based on score trajectory."""
        snapshots = self.history["snapshots"]
        
        for entry in edge_map:
            cluster = entry["cluster"]
            current_score = entry["score"]
            tested = entry.get("tested", 0)
            
            # Get score history for this cluster
            score_history = []
            for snap in snapshots[-10:]:  # last 10 snapshots
                score_history.append(snap["scores"].get(cluster, 0))
            
            # Determine lifecycle stage
            stage = self._classify_stage(current_score, score_history, tested)
            
            prev = self.lifecycle["clusters"].get(cluster, {})
            prev_stage = prev.get("stage", "")
            cycles_in_stage = prev.get("cycles_in_stage", 0)
            
            if stage == prev_stage:
                cycles_in_stage += 1
            else:
                cycles_in_stage = 1
            
            self.lifecycle["clusters"][cluster] = {
                "stage": stage,
                "emoji": STAGES.get(stage, "❓"),
                "current_score": current_score,
                "cycles_in_stage": cycles_in_stage,
                "tested": tested,
                "score_trend": self._trend(score_history),
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
        
        self.lifecycle["last_updated"] = datetime.now(timezone.utc).isoformat()
        self._save_lifecycle()
    
    def _classify_stage(self, current: float, history: List[float], tested: int) -> str:
        """Classify cluster lifecycle stage."""
        if tested < 5:
            return "BIRTH"
        
        if len(history) < 3:
            return "GROWING" if current > 0.1 else "BIRTH"
        
        recent = history[-3:]
        avg_recent = sum(recent) / len(recent)
        older = history[:-3] if len(history) > 3 else history[:1]
        avg_older = sum(older) / len(older) if older else 0
        
        # Dead: very low score with many tests
        if current < 0.05 and tested >= 20:
            # Check if reviving
            if len(history) >= 4 and recent[-1] > recent[0] * 1.5:
                return "REVIVING"
            return "DEAD"
        
        # Declining: score dropping
        if avg_older > 0 and avg_recent < avg_older * 0.7:
            return "DECLINING"
        
        # Growing: score increasing
        if avg_recent > avg_older * 1.1 and current > 0.2:
            return "GROWING"
        
        # Peak: high score, stable
        if current > 0.5 and abs(avg_recent - avg_older) / max(avg_older, 0.01) < 0.15:
            return "PEAK"
        
        # Default
        if current > 0.3:
            return "GROWING"
        
        return "DECLINING"
    
    def _trend(self, history: List[float]) -> str:
        """Simple trend direction."""
        if len(history) < 2:
            return "flat"
        recent = history[-2:]
        if recent[-1] > recent[0] * 1.05:
            return "up"
        elif recent[-1] < recent[0] * 0.95:
            return "down"
        return "flat"
    
    def get_summary(self) -> Dict:
        """Get lifecycle summary for logging/display."""
        stage_counts = {}
        for cluster, data in self.lifecycle.get("clusters", {}).items():
            stage = data.get("stage", "?")
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
        
        # Get clusters by stage
        by_stage = {}
        for cluster, data in self.lifecycle.get("clusters", {}).items():
            stage = data.get("stage", "?")
            if stage not in by_stage:
                by_stage[stage] = []
            by_stage[stage].append({
                "cluster": cluster,
                "score": data.get("current_score", 0),
                "cycles": data.get("cycles_in_stage", 0),
            })
        
        return {
            "stage_counts": stage_counts,
            "by_stage": by_stage,
            "total_tracked": len(self.lifecycle.get("clusters", {})),
        }
    
    def _save_history(self):
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(HISTORY_PATH, "w") as f:
            json.dump(self.history, f, indent=2, default=str)
    
    def _save_lifecycle(self):
        LIFECYCLE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LIFECYCLE_PATH, "w") as f:
            json.dump(self.lifecycle, f, indent=2, default=str)


# Singleton
_tracker = None
def get_tracker() -> ClusterLifecycle:
    global _tracker
    if _tracker is None:
        _tracker = ClusterLifecycle()
    return _tracker
