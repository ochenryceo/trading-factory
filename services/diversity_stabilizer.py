"""
Diversity Stabilizer — Self-correcting evolutionary diversity governor.

Monitors 4 signals every generation:
  1. Style dominance (is one archetype taking over?)
  2. Parameter variance (are params collapsing to same values?)
  3. Lineage concentration (is one family dominating?)
  4. Near-miss quality (is the evolutionary future degrading?)

Applies graduated corrections:
  - Nudges, not overrides (10-30% adjustments)
  - Decays automatically when healthy
  - Governor, not controller

Sits between: Results → Metrics → [DIVERSITY STABILIZER] → Control Layer → Next Gen
"""

import json
import logging
import math
from pathlib import Path
from datetime import datetime, timezone

log = logging.getLogger("diversity_stabilizer")

BASE_DIR = Path("Path(__file__).resolve().parents[1]")
NEAR_MISS_FILE = BASE_DIR / "data" / "near_misses.jsonl"
OUTPUT_JSONL = BASE_DIR / "data" / "continuous_run_log.jsonl"
LINEAGE_FILE = BASE_DIR / "data" / "lineage_scores.json"
DISCOVERY_RATE_FILE = BASE_DIR / "data" / "discovery_rate.jsonl"
STABILIZER_LOG = BASE_DIR / "data" / "diversity_stabilizer.jsonl"
STABILIZER_STATE = BASE_DIR / "data" / "diversity_stabilizer_state.json"


# ─── Thresholds ────────────────────────────────────────────────────────────

STYLE_DOMINANT_THRESHOLD = 0.70      # style > 70% = dominant
STYLE_SEVERE_THRESHOLD = 0.80        # style > 80% = severe
LINEAGE_DOMINANT_THRESHOLD = 0.60    # top family > 60% = lineage collapse
PARAM_CONVERGENCE_THRESHOLD = 0.15   # relative std < 15% = converging
NM_SHARPE_WEAK = 0.70               # near-miss avg sharpe < 0.7 = weak
NM_SHARPE_CRITICAL = 0.50           # near-miss avg sharpe < 0.5 = critical
NM_TRADES_WEAK = 40                 # near-miss avg trades < 40 = low frequency


# ─── State Management ──────────────────────────────────────────────────────

def _load_state() -> dict:
    if STABILIZER_STATE.exists():
        try:
            return json.load(open(STABILIZER_STATE))
        except Exception:
            pass
    return {
        "style_weight_adjustments": {},
        "exploration_boost": 0.0,
        "bias_penalty_boost": 0.0,
        "forced_diversity_seeds": 0,
        "shock_override": False,
        "nm_protect_non_dominant": False,
        "consecutive_dominant": 0,
        "consecutive_weak_nm": 0,
        "last_state": "healthy",
    }


def _save_state(state: dict):
    STABILIZER_STATE.parent.mkdir(parents=True, exist_ok=True)
    with open(STABILIZER_STATE, "w") as f:
        json.dump(state, f, indent=2)


def _log_event(event: dict):
    STABILIZER_LOG.parent.mkdir(parents=True, exist_ok=True)
    event["timestamp"] = datetime.now(timezone.utc).isoformat()
    with open(STABILIZER_LOG, "a") as f:
        f.write(json.dumps(event, default=str) + "\n")


# ─��─ Signal Computation ───────────────────────────────────────────────────

def compute_signals() -> dict:
    """Compute all 4 diversity signals from current data."""
    signals = {
        "style_dominance": 0.0,
        "dominant_style": "none",
        "style_distribution": {},
        "param_variance": 1.0,
        "lineage_concentration": 0.0,
        "top_lineage": "none",
        "nm_avg_sharpe": 0.5,
        "nm_avg_trades": 30,
        "nm_count": 0,
    }

    # 1. Style dominance — from discovery rate log
    try:
        if DISCOVERY_RATE_FILE.exists():
            lines = open(DISCOVERY_RATE_FILE).readlines()
            if lines:
                last = json.loads(lines[-1].strip())
                signals["style_dominance"] = last.get("style_dominance", 0)
                signals["dominant_style"] = last.get("dominant_style", "none")
                signals["style_distribution"] = last.get("style_distribution", {})
    except Exception:
        pass

    # 2. Parameter variance — from recent results
    try:
        if OUTPUT_JSONL.exists():
            import numpy as np
            lines = open(OUTPUT_JSONL).readlines()
            param_stds = []
            for line in lines[-200:]:
                try:
                    d = json.loads(line.strip())
                    # Can't read raw params from results, use proxy: sharpe + trades spread
                    pass
                except Exception:
                    pass

            # Use fitness std as proxy for parameter diversity
            if lines:
                last_dr = None
                try:
                    dr_lines = open(DISCOVERY_RATE_FILE).readlines()
                    if dr_lines:
                        last_dr = json.loads(dr_lines[-1].strip())
                except Exception:
                    pass
                if last_dr:
                    signals["param_variance"] = last_dr.get("fitness_std", 0.1)
    except Exception:
        pass

    # 3. Lineage concentration
    try:
        if LINEAGE_FILE.exists():
            lineage = json.load(open(LINEAGE_FILE))
            if lineage:
                total_count = sum(v.get("count", 0) for v in lineage.values())
                if total_count > 0:
                    top_family = max(lineage.items(), key=lambda x: x[1].get("count", 0))
                    signals["lineage_concentration"] = top_family[1].get("count", 0) / total_count
                    signals["top_lineage"] = top_family[0]
    except Exception:
        pass

    # 4. Near-miss quality (last 50)
    try:
        if NEAR_MISS_FILE.exists():
            nm_lines = open(NEAR_MISS_FILE).readlines()
            recent = []
            for line in nm_lines[-50:]:
                try:
                    recent.append(json.loads(line.strip()))
                except Exception:
                    pass
            if recent:
                signals["nm_avg_sharpe"] = sum(n.get("sharpe", 0) for n in recent) / len(recent)
                signals["nm_avg_trades"] = sum(n.get("trades", 0) for n in recent) / len(recent)
                signals["nm_count"] = len(recent)
    except Exception:
        pass

    return signals


# ─── Detection ─────────────────────────────────────────────────────────────

def detect_state(signals: dict) -> str:
    """Determine diversity health state from signals."""

    sd = signals["style_dominance"]
    lc = signals["lineage_concentration"]
    nm_s = signals["nm_avg_sharpe"]
    nm_t = signals["nm_avg_trades"]
    pv = signals["param_variance"]

    # Severity order: most dangerous first
    if sd >= STYLE_SEVERE_THRESHOLD:
        return "severe_dominance"

    if sd >= STYLE_DOMINANT_THRESHOLD and nm_s < NM_SHARPE_CRITICAL:
        return "convergence_collapse"

    if lc >= LINEAGE_DOMINANT_THRESHOLD:
        return "lineage_collapse"

    if sd >= STYLE_DOMINANT_THRESHOLD:
        return "dominant_style"

    if nm_s < NM_SHARPE_WEAK and nm_t < NM_TRADES_WEAK:
        return "exploration_weak"

    if pv < PARAM_CONVERGENCE_THRESHOLD:
        return "param_convergence"

    return "healthy"


# ─── Correction Actions ───────────────────────────────────────────────────

def compute_corrections(state_name: str, signals: dict, stabilizer_state: dict) -> dict:
    """
    Compute graduated corrections based on detected state.
    Returns adjustments dict to apply to control layer.
    """
    adj = {
        "style_weight_adjustments": {},
        "exploration_boost": 0.0,
        "bias_penalty_boost": 0.0,
        "forced_diversity_seeds": 0,
        "shock_override": False,
        "nm_protect_non_dominant": False,
    }

    dominant = signals["dominant_style"]
    non_dominant = [s for s in signals["style_distribution"].keys() if s != dominant]

    if state_name == "severe_dominance":
        # A. Reduce dominant style -30%, boost minorities +20%
        adj["style_weight_adjustments"][dominant] = -0.30
        for s in non_dominant:
            adj["style_weight_adjustments"][s] = 0.20
        # C. 4 forced diversity seeds
        adj["forced_diversity_seeds"] = 4
        # D. Shock override
        adj["shock_override"] = True
        # E. Flatten bias hard
        adj["bias_penalty_boost"] = 0.25
        # F. Protect near-miss diversity
        adj["nm_protect_non_dominant"] = True
        # B. Exploration boost
        adj["exploration_boost"] = 0.12

    elif state_name == "convergence_collapse":
        adj["style_weight_adjustments"][dominant] = -0.25
        for s in non_dominant:
            adj["style_weight_adjustments"][s] = 0.15
        adj["forced_diversity_seeds"] = 3
        adj["shock_override"] = True
        adj["bias_penalty_boost"] = 0.20
        adj["nm_protect_non_dominant"] = True
        adj["exploration_boost"] = 0.10

    elif state_name == "lineage_collapse":
        # Focus on breaking lineage, not style
        adj["forced_diversity_seeds"] = 3
        adj["exploration_boost"] = 0.08
        adj["bias_penalty_boost"] = 0.10

    elif state_name == "dominant_style":
        adj["style_weight_adjustments"][dominant] = -0.15
        for s in non_dominant:
            adj["style_weight_adjustments"][s] = 0.10
        adj["forced_diversity_seeds"] = 2
        adj["exploration_boost"] = 0.05
        adj["nm_protect_non_dominant"] = True

    elif state_name == "exploration_weak":
        adj["forced_diversity_seeds"] = 2
        adj["exploration_boost"] = 0.05
        adj["nm_protect_non_dominant"] = True

    elif state_name == "param_convergence":
        adj["shock_override"] = True
        adj["exploration_boost"] = 0.05

    else:  # healthy
        pass

    return adj


# ─── Decay Logic ───────────────────────────────────────────────────────────

def apply_decay(stabilizer_state: dict) -> dict:
    """Gradually decay all corrections back to zero when healthy."""
    decay_rate = 0.15  # 15% decay per generation

    swa = stabilizer_state.get("style_weight_adjustments", {})
    for style in list(swa.keys()):
        if abs(swa[style]) < 0.02:
            del swa[style]
        else:
            swa[style] *= (1.0 - decay_rate)
    stabilizer_state["style_weight_adjustments"] = swa

    for key in ("exploration_boost", "bias_penalty_boost"):
        val = stabilizer_state.get(key, 0)
        if abs(val) < 0.01:
            stabilizer_state[key] = 0
        else:
            stabilizer_state[key] *= (1.0 - decay_rate)

    stabilizer_state["forced_diversity_seeds"] = 0
    stabilizer_state["shock_override"] = False
    stabilizer_state["nm_protect_non_dominant"] = False

    return stabilizer_state


# ─── Main Entry Point ─────────────────────────────────────────────────────

def run_stabilizer() -> dict:
    """
    Run the diversity stabilizer. Call once per generation.
    Returns the current adjustments dict for the control layer to consume.
    """
    state = _load_state()
    signals = compute_signals()
    detected = detect_state(signals)

    # Track consecutive states
    if detected in ("dominant_style", "severe_dominance", "convergence_collapse"):
        state["consecutive_dominant"] = state.get("consecutive_dominant", 0) + 1
    else:
        state["consecutive_dominant"] = max(0, state.get("consecutive_dominant", 0) - 1)

    if detected in ("exploration_weak", "convergence_collapse"):
        state["consecutive_weak_nm"] = state.get("consecutive_weak_nm", 0) + 1
    else:
        state["consecutive_weak_nm"] = max(0, state.get("consecutive_weak_nm", 0) - 1)

    if detected == "healthy":
        # Decay existing corrections
        state = apply_decay(state)
        log.info(f"🌿 STABILIZER: healthy — decaying corrections")
    else:
        # Compute and apply corrections
        corrections = compute_corrections(detected, signals, state)

        # Merge corrections into state (additive, capped)
        swa = state.get("style_weight_adjustments", {})
        for style, delta in corrections["style_weight_adjustments"].items():
            current = swa.get(style, 0)
            swa[style] = max(-0.50, min(0.30, current + delta))
        state["style_weight_adjustments"] = swa

        state["exploration_boost"] = min(0.20, state.get("exploration_boost", 0) + corrections["exploration_boost"])
        state["bias_penalty_boost"] = min(0.30, state.get("bias_penalty_boost", 0) + corrections["bias_penalty_boost"])
        state["forced_diversity_seeds"] = corrections["forced_diversity_seeds"]
        state["shock_override"] = corrections["shock_override"]
        state["nm_protect_non_dominant"] = corrections["nm_protect_non_dominant"]

        log.warning(
            f"🔧 STABILIZER [{detected}]: dom={signals['dominant_style']}@{signals['style_dominance']:.0%} "
            f"nm_sharpe={signals['nm_avg_sharpe']:.2f} nm_trades={signals['nm_avg_trades']:.0f} "
            f"lineage={signals['lineage_concentration']:.0%} "
            f"→ explore+{state['exploration_boost']:.0%} seeds={state['forced_diversity_seeds']} "
            f"shock={state['shock_override']}"
        )

    state["last_state"] = detected
    _save_state(state)

    # Log event for dashboard
    _log_event({
        "state": detected,
        "signals": {k: round(v, 4) if isinstance(v, float) else v for k, v in signals.items()},
        "corrections": {
            "style_adjustments": state.get("style_weight_adjustments", {}),
            "exploration_boost": round(state.get("exploration_boost", 0), 4),
            "bias_penalty_boost": round(state.get("bias_penalty_boost", 0), 4),
            "forced_seeds": state.get("forced_diversity_seeds", 0),
            "shock": state.get("shock_override", False),
            "nm_protect": state.get("nm_protect_non_dominant", False),
        },
        "consecutive_dominant": state.get("consecutive_dominant", 0),
        "consecutive_weak_nm": state.get("consecutive_weak_nm", 0),
    })

    return {
        "style_weight_adjustments": state.get("style_weight_adjustments", {}),
        "exploration_boost": state.get("exploration_boost", 0),
        "bias_penalty_boost": state.get("bias_penalty_boost", 0),
        "forced_diversity_seeds": state.get("forced_diversity_seeds", 0),
        "shock_override": state.get("shock_override", False),
        "nm_protect_non_dominant": state.get("nm_protect_non_dominant", False),
    }
