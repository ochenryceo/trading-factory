"""
Search Space Expansion Module — Controlled Evolutionary Space Growth
=====================================================================
When the system hits search space saturation (stagnation_counter ≥ threshold),
this module activates new dimensions for evolution to explore WITHOUT loosening
quality standards.

What it DOES:
  - Adds new timeframes (5m, 30m)
  - Adds session filters (London/NY open bias)
  - Adds volatility regime awareness (ATR-based entry gating)
  - Adds dynamic thresholds (adaptive RSI/BB based on vol regime)
  - Controls expansion ratio (20% expanded / 80% original)

What it does NOT do:
  - Change fitness weights
  - Weaken Darwin criteria
  - Lower sanity filters
  - Modify frequency module

Integration:
  - Called by generate_batch_dnas() to produce expanded-space strategies
  - Called by _create_batches() to include new timeframes
  - Called by _generate_signals() to apply expanded signal logic
  - Reads/writes expansion_state.json for persistence

Trigger:
  stagnation_counter ≥ STAGNATION_TRIGGER AND discovery_rate == 0

Author: Henry (autonomous build)
Date: 2026-03-26
"""

import json
import logging
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("search_expansion")

BASE_DIR = Path("Path(__file__).resolve().parents[1]")
DATA_DIR = BASE_DIR / "data" / "processed"
EXPANSION_STATE_FILE = BASE_DIR / "data" / "expansion_state.json"
CONTROL_STATE_FILE = BASE_DIR / "data" / "control_state.json"
EXPANSION_LOG_FILE = BASE_DIR / "data" / "expansion_log.jsonl"

# ─── Configuration ──────────────────────────────────────────────────────────

STAGNATION_TRIGGER = 500          # activate at this stagnation count
DISCOVERY_RATE_TRIGGER = 0.0      # AND discovery rate must be zero

EXPANSION_STRENGTH_STEP = 0.05    # ramp per activation check (slow stable ramp)
EXPANSION_STRENGTH_MAX = 0.50     # cap at 50% of batch
EXPANSION_DECAY_FACTOR = 0.90     # decay when discovery recovers

# New timeframes to add (data must exist as parquet)
EXPANDED_TIMEFRAMES = ["5m", "30m"]

# New parameter ranges for expanded dimensions
EXPANDED_PARAM_RANGES = {
    # Session filter: hour of day (UTC) for session-biased entries
    "session_filter_start": (0, 23),       # start hour
    "session_filter_end": (1, 24),         # end hour (can wrap)
    "session_filter_enabled": (0, 1),      # 0=off, 1=on

    # Volatility regime: ATR-based gating
    "atr_regime_period": (10, 50),         # ATR lookback
    "atr_regime_percentile": (30, 80),     # min ATR percentile to trade
    "atr_regime_enabled": (0, 1),          # 0=off, 1=on

    # Dynamic thresholds: scale entry levels by volatility
    "dynamic_threshold_scale": (0.5, 2.0), # multiplier on base thresholds
    "dynamic_threshold_enabled": (0, 1),   # 0=off, 1=on
}

# Pre-defined session windows (UTC hours)
SESSION_WINDOWS = {
    "london_open":   (7, 12),     # London 07:00-12:00 UTC
    "ny_open":       (13, 17),    # NY 13:00-17:00 UTC (after US open)
    "asia_session":  (23, 6),     # Asia 23:00-06:00 UTC (wraps midnight)
    "london_ny_overlap": (13, 16), # Overlap 13:00-16:00 UTC
    "us_morning":    (13, 16),    # First 3h of US session
}


# ─── State Management ──────────────────────────────────────────────────────

def load_expansion_state() -> dict:
    """Load expansion state from disk."""
    if EXPANSION_STATE_FILE.exists():
        try:
            with open(EXPANSION_STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "active": False,
        "activated_at": None,
        "activated_generation": None,
        "expansion_strength": 0.0,
        "features_enabled": [],
        "strategies_tested_expanded": 0,
        "strategies_passed_expanded": 0,
        "total_activations": 0,
    }


def save_expansion_state(state: dict):
    """Persist expansion state."""
    EXPANSION_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(EXPANSION_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _log_expansion_event(event: str, details: dict = None):
    """Append to expansion log."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **(details or {}),
    }
    EXPANSION_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(EXPANSION_LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    log.info(f"🔬 EXPANSION: {event} | {details or ''}")


# ─── Trigger Detection ─────────────────────────────────────────────────────

def _load_control_state() -> dict:
    """Read control layer state."""
    if CONTROL_STATE_FILE.exists():
        try:
            with open(CONTROL_STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def should_activate() -> bool:
    """
    Check if expansion should activate.
    
    Trigger: stagnation_counter >= STAGNATION_TRIGGER
             AND last 10 discovery rates are all 0
    """
    cs = _load_control_state()
    stagnation = cs.get("stagnation_counter", 0)
    rates = cs.get("last_discovery_rates", [])

    # Both conditions must be true
    stagnation_met = stagnation >= STAGNATION_TRIGGER
    discovery_dead = len(rates) >= 10 and all(r == 0 for r in rates[-10:])

    return stagnation_met and discovery_dead


def check_and_activate(generation: int) -> dict:
    """
    Main entry point — called every generation by the supervisor.
    Returns expansion state (active or not).
    """
    state = load_expansion_state()

    if state["active"]:
        # Already active — just return current state
        return state

    if should_activate():
        # TRIGGER GUARD: verify EXPANSION_READY before allowing activation
        if not state.get("validated_ready", False):
            # Check if validation was ever run successfully
            ready_logged = False
            if EXPANSION_LOG_FILE.exists():
                try:
                    with open(EXPANSION_LOG_FILE) as f:
                        for line in f:
                            if '"EXPANSION_READY"' in line:
                                ready_logged = True
                except Exception:
                    pass

            if not ready_logged:
                _log_expansion_event("EXPANSION_BLOCKED", {
                    "reason": "EXPANSION_READY not confirmed — trigger guard blocked activation",
                    "stagnation": _load_control_state().get("stagnation_counter", 0),
                })
                log.error(
                    "🚨 TRIGGER GUARD: Expansion triggered at stagnation >= 500 "
                    "but EXPANSION_READY was never confirmed. BLOCKED. "
                    "Restart backtester and run validate_ready() first."
                )
                return state
            else:
                state["validated_ready"] = True
                save_expansion_state(state)

        if not state["active"]:
            # First activation
            state["active"] = True
            state["activated_at"] = datetime.now(timezone.utc).isoformat()
            state["activated_generation"] = generation
            state["total_activations"] = state.get("total_activations", 0) + 1
            state["features_enabled"] = [
                "timeframe_5m",
                "timeframe_30m",
                "session_filters",
                "atr_regime",
                "dynamic_thresholds",
                "holding_time",
            ]
            _log_expansion_event("ACTIVATED", {
                "generation": generation,
                "stagnation_counter": _load_control_state().get("stagnation_counter", 0),
                "features": state["features_enabled"],
            })
            log.warning(f"🔬🔬🔬 SEARCH EXPANSION ACTIVATED at gen {generation} 🔬🔬🔬")
            # Code hash for version trace
            import hashlib
            try:
                with open(Path(__file__).resolve(), "rb") as fh:
                    code_hash = hashlib.sha256(fh.read()).hexdigest()[:12]
            except Exception:
                code_hash = "unknown"
            _log_expansion_event("EXPANSION_TRIGGERED", {
                "generation": generation,
                "stagnation_counter": _load_control_state().get("stagnation_counter", 0),
                "strength": state.get("expansion_strength", 0.0),
                "code_hash": code_hash,
            })

        # Ramp strength gradually (each gen while stagnation persists)
        state["expansion_strength"] = min(
            EXPANSION_STRENGTH_MAX,
            state.get("expansion_strength", 0.0) + EXPANSION_STRENGTH_STEP,
        )
        save_expansion_state(state)
        log.info(f"🔬 Expansion strength: {state['expansion_strength']:.0%}")

    return state


# ─── Data Preparation ──────────────────────────────────────────────────────

def ensure_30m_data():
    """
    Generate 30m parquet files by resampling 5m data.
    Only runs if 30m doesn't exist but 5m does.
    """
    import pandas as pd

    for asset in ["NQ", "GC", "CL"]:
        src = DATA_DIR / asset / "5m.parquet"
        dst = DATA_DIR / asset / "30m.parquet"

        if dst.exists():
            continue
        if not src.exists():
            log.warning(f"Cannot create 30m for {asset}: no 5m data")
            continue

        try:
            df = pd.read_parquet(src)
            # Resample 5m → 30m using OHLCV aggregation
            resampled = df.resample("30min").agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }).dropna()
            resampled.to_parquet(dst)
            log.info(f"Created 30m data for {asset}: {len(resampled)} bars from {len(df)} 5m bars")
            _log_expansion_event("DATA_CREATED", {
                "asset": asset,
                "timeframe": "30m",
                "bars": len(resampled),
                "source_bars": len(df),
            })
        except Exception as e:
            log.error(f"Failed to create 30m for {asset}: {e}")


# ─── Expanded Timeframes ───────────────────────────────────────────────────

def get_active_timeframes(original_timeframes: list[str]) -> list[str]:
    """
    Return timeframes to use. If expansion active, add new ones.
    """
    state = load_expansion_state()
    if not state["active"]:
        return original_timeframes

    expanded = list(original_timeframes)
    for tf in EXPANDED_TIMEFRAMES:
        if tf not in expanded:
            # Verify data exists for at least one asset
            has_data = any(
                (DATA_DIR / asset / f"{tf}.parquet").exists()
                for asset in ["NQ", "GC", "CL"]
            )
            if has_data:
                expanded.append(tf)

    return expanded


# ─── Expanded DNA Generation ───────────────────────────────────────────────

def expanded_random_params(style: str, base_params: dict) -> dict:
    """
    Add expansion dimensions to a strategy's parameters.
    
    Takes base params (from normal generation) and adds:
    - Session filter params (probabilistic — not always enabled)
    - ATR regime params
    - Dynamic threshold params
    """
    params = dict(base_params)

    # Session filters — adaptive probability based on recent signal density
    # If many strategies are too_sparse, reduce filter aggression
    session_prob = 0.60
    try:
        ctrl = _load_control_state()
        # High stagnation + low discovery = signals already scarce, filter less
        if ctrl.get("stagnation_counter", 0) > 600:
            session_prob = 0.40
    except Exception:
        pass
    if random.random() < session_prob:
        params["session_filter_enabled"] = 1
        # Pick a session window
        session = random.choice(list(SESSION_WINDOWS.keys()))
        start, end = SESSION_WINDOWS[session]
        params["session_filter_start"] = start
        params["session_filter_end"] = end
        params["session_name"] = session  # metadata, not used in signals
    else:
        params["session_filter_enabled"] = 0
        params["session_filter_start"] = 0
        params["session_filter_end"] = 24

    # ATR regime — 50% chance (percentile-based, relative to market behavior)
    if random.random() < 0.50:
        params["atr_regime_enabled"] = 1
        params["atr_regime_period"] = random.randint(10, 50)
        params["atr_regime_percentile"] = random.randint(60, 90)
    else:
        params["atr_regime_enabled"] = 0
        params["atr_regime_period"] = 14
        params["atr_regime_percentile"] = 50

    # Dynamic thresholds — 40% chance (conservative multiplier range)
    if random.random() < 0.40:
        params["dynamic_threshold_enabled"] = 1
        params["dynamic_threshold_scale"] = round(random.uniform(0.7, 1.5), 2)
    else:
        params["dynamic_threshold_enabled"] = 0
        params["dynamic_threshold_scale"] = 1.0

    # Holding time flexibility — always enabled for expanded strategies
    params["max_hold_bars"] = random.randint(10, 150)
    params["max_hold_enabled"] = 1

    return params


def should_expand_strategy(batch_index: int, batch_size: int) -> bool:
    """
    Determine if this strategy slot should use expanded space.
    Uses expansion_strength (0.0-0.5) to decide proportion.
    Probabilistic: each slot rolls against strength.
    """
    state = load_expansion_state()
    if not state["active"]:
        return False

    strength = state.get("expansion_strength", 0.0)
    return random.random() < strength


# ─── Expanded Signal Generation ────────────────────────────────────────────

def apply_session_filter(
    entry_signals: "np.ndarray",
    timestamps: "np.ndarray",
    params: dict,
) -> "np.ndarray":
    """
    Zero out entry signals outside the configured session window.
    Only applies if session_filter_enabled == 1.
    """
    import numpy as np

    if params.get("session_filter_enabled", 0) != 1:
        return entry_signals

    start_hour = params.get("session_filter_start", 0)
    end_hour = params.get("session_filter_end", 24)

    # Extract hours from timestamps
    try:
        if hasattr(timestamps[0], 'hour'):
            hours = np.array([t.hour for t in timestamps])
        else:
            # Timestamps might be numpy datetime64
            import pandas as pd
            hours = pd.DatetimeIndex(timestamps).hour.values
    except Exception:
        return entry_signals  # fail open — don't filter if we can't parse

    # Create session mask
    if start_hour < end_hour:
        # Normal window (e.g., 7-12)
        session_mask = (hours >= start_hour) & (hours < end_hour)
    else:
        # Wrapping window (e.g., 23-6)
        session_mask = (hours >= start_hour) | (hours < end_hour)

    # Zero out entries outside session
    filtered = entry_signals.copy()
    filtered[~session_mask] = False
    return filtered


def apply_atr_regime(
    entry_signals: "np.ndarray",
    high: "np.ndarray",
    low: "np.ndarray",
    close: "np.ndarray",
    params: dict,
) -> "np.ndarray":
    """
    Zero out entry signals when ATR is below the required percentile.
    Only trades during 'active' volatility regimes.
    """
    import numpy as np

    if params.get("atr_regime_enabled", 0) != 1:
        return entry_signals

    period = params.get("atr_regime_period", 14)
    pct_threshold = params.get("atr_regime_percentile", 50)

    # Compute ATR
    n = len(close)
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1])
        )
    )
    tr = np.concatenate([[tr[0] if len(tr) > 0 else 0], tr])

    # Smoothed ATR (EMA)
    atr = np.zeros(n)
    atr[0] = tr[0]
    alpha = 2 / (period + 1)
    for i in range(1, n):
        atr[i] = alpha * tr[i] + (1 - alpha) * atr[i - 1]

    # Rolling percentile of ATR (last 200 bars)
    window = min(200, n)
    atr_pct = np.zeros(n)
    for i in range(window, n):
        chunk = atr[i - window:i]
        atr_pct[i] = (np.sum(chunk < atr[i]) / len(chunk)) * 100

    # Only trade when current ATR percentile >= threshold
    regime_mask = atr_pct >= pct_threshold

    filtered = entry_signals.copy()
    filtered[~regime_mask] = False
    return filtered


def apply_dynamic_thresholds(params: dict) -> dict:
    """
    Scale base threshold parameters by the dynamic scale factor.
    Returns modified params (does not mutate original).
    
    This makes RSI thresholds, z-score thresholds etc. adaptive
    rather than static — higher scale = looser entry, lower = tighter.
    """
    if params.get("dynamic_threshold_enabled", 0) != 1:
        return params

    scale = params.get("dynamic_threshold_scale", 1.0)
    scaled = dict(params)

    # Scale threshold-type params (conservative bounds to prevent instability)
    if "rsi_threshold" in scaled:
        base = scaled["rsi_threshold"]
        scaled["rsi_threshold"] = int(max(20, min(45, base * scale)))

    if "z_score_threshold" in scaled:
        base = scaled["z_score_threshold"]
        scaled["z_score_threshold"] = round(max(0.8, min(3.5, base / scale)), 2)

    if "adx_threshold" in scaled:
        base = scaled["adx_threshold"]
        scaled["adx_threshold"] = int(max(10, min(35, base / scale)))

    return scaled


# ─── Batch Integration ─────────────────────────────────────────────────────

def get_expanded_timeframe_batches(
    generation: int,
    original_timeframes: list[str],
    assets: list[str],
) -> list[str]:
    """
    Return additional (asset, timeframe) pairs for expanded batches.
    These are ON TOP of the original batches, not replacing them.
    """
    state = load_expansion_state()
    if not state["active"]:
        return []

    extra = []
    for tf in EXPANDED_TIMEFRAMES:
        if tf in original_timeframes:
            continue
        for asset in assets:
            if (DATA_DIR / asset / f"{tf}.parquet").exists():
                extra.append((asset, tf))

    return extra


# ─── Expansion Metrics ─────────────────────────────────────────────────────

def track_expanded_result(passed: bool, strategy_code: str = ""):
    """Track how expanded strategies are performing."""
    state = load_expansion_state()
    if not state["active"]:
        return

    state["strategies_tested_expanded"] = state.get("strategies_tested_expanded", 0) + 1
    if passed:
        state["strategies_passed_expanded"] = state.get("strategies_passed_expanded", 0) + 1

    save_expansion_state(state)


def get_expansion_stats() -> dict:
    """Get expansion performance summary including lineage emergence."""
    state = load_expansion_state()
    tested = state.get("strategies_tested_expanded", 0)
    passed = state.get("strategies_passed_expanded", 0)

    # Track new lineages born after expansion activation
    new_lineages = []
    activated_gen = state.get("activated_generation", 0)
    if activated_gen and state.get("active"):
        try:
            import json as _json
            lineage_file = BASE_DIR / "data" / "lineage_scores.json"
            backtester_state = BASE_DIR / "data" / "backtester_v2_state.json"
            current_gen = 0
            if backtester_state.exists():
                with open(backtester_state) as f:
                    current_gen = _json.load(f).get("generation", 0)

            if lineage_file.exists():
                with open(lineage_file) as f:
                    lineages = _json.load(f)
                for lid, ldata in lineages.items():
                    if isinstance(ldata, dict):
                        gens = ldata.get("generations", [])  # fitness per offspring
                        count = ldata.get("count", 0)
                        best = ldata.get("best", 0)
                        # Young lineage (<=8 offspring) = likely born post-expansion
                        if count >= 1 and count <= 8:
                            # 1: Survival depth = offspring count
                            survival_depth = count

                            # 2: Momentum = growth trend (last 3 vs first 3 fitness)
                            momentum = 0.0
                            if len(gens) >= 4:
                                half = len(gens) // 2
                                early = sum(gens[:half]) / half
                                late = sum(gens[half:]) / (len(gens) - half)
                                momentum = round(late - early, 3)  # positive = improving

                            # 5: Kill fake survival — best fitness must be >= 0.55
                            quality_pass = best >= 0.55

                            # Surviving = 2+ offspring AND quality pass
                            surviving = survival_depth >= 2 and quality_pass

                            # Infer style from lineage ID prefix
                            style = lid.split("-")[0] if "-" in lid else "unknown"

                            new_lineages.append({
                                "id": lid,
                                "count": count,
                                "best": best,
                                "survival_depth": survival_depth,
                                "surviving": surviving,
                                "momentum": momentum,
                                "quality_pass": quality_pass,
                                "style": style,
                            })
        except Exception:
            pass

    # Classify expansion signal strength
    surviving_lineages = [l for l in new_lineages if l["surviving"]]
    gens_since_activation = (current_gen - activated_gen) if activated_gen and state.get("active") else 0

    # 4: Cross-style diversity — are surviving lineages from different styles?
    surviving_styles = set(l["style"] for l in surviving_lineages)
    cross_style = len(surviving_styles) >= 2

    # 3: Time-to-survival (gens since activation to first surviving lineage)
    # Approximated: if we have survivors, earliest = fewest offspring (youngest)
    time_to_survival = None
    if surviving_lineages:
        # Rough proxy: surviving lineage with fewest offspring appeared most recently
        min_depth = min(l["survival_depth"] for l in surviving_lineages)
        time_to_survival = max(1, gens_since_activation - min_depth * 2)  # estimate

    if len(surviving_lineages) >= 2 and cross_style and gens_since_activation <= 30:
        signal_strength = "STRONG"
    elif len(surviving_lineages) >= 2 and gens_since_activation <= 30:
        signal_strength = "MODERATE"  # survivors but same style = not true diversity
    elif len(surviving_lineages) == 1:
        signal_strength = "WEAK"
    elif gens_since_activation >= 50 and len(surviving_lineages) == 0:
        signal_strength = "EXHAUSTED"
    else:
        signal_strength = "WATCHING"

    return {
        "active": state.get("active", False),
        "activated_at": state.get("activated_at"),
        "activated_generation": state.get("activated_generation"),
        "features": state.get("features_enabled", []),
        "tested": tested,
        "passed": passed,
        "pass_rate": passed / max(tested, 1),
        "expansion_strength": state.get("expansion_strength", 0.0),
        "new_lineages": new_lineages,
        "new_lineage_count": len(new_lineages),
        "surviving_lineage_count": len(surviving_lineages),
        "surviving_styles": list(surviving_styles),
        "cross_style_diversity": cross_style,
        "time_to_survival": time_to_survival,
        "signal_strength": signal_strength,
        "gens_since_activation": gens_since_activation,
    }


# ─── Deactivation ──────────────────────────────────────────────────────────

def check_deactivation():
    """
    Gradual decay: when discovery recovers, strength *= 0.9 each gen.
    Shuts off when strength drops below 0.05.
    
    When deactivated, successful expanded dimensions get absorbed
    into the main search space permanently.
    """
    state = load_expansion_state()
    if not state["active"]:
        return

    cs = _load_control_state()
    rates = cs.get("last_discovery_rates", [])

    # If discovery is recovering (any > 0 in last 5 windows), decay strength
    if len(rates) >= 5 and any(r > 0 for r in rates[-5:]):
        old_strength = state.get("expansion_strength", 0.0)
        state["expansion_strength"] = old_strength * EXPANSION_DECAY_FACTOR

        if state["expansion_strength"] < 0.05:
            # Fully decayed — deactivate
            activated_gen = state.get("activated_generation", 0)
            _log_expansion_event("DEACTIVATED_DECAYED", {
                "final_strength": state["expansion_strength"],
                "expanded_tested": state.get("strategies_tested_expanded", 0),
                "expanded_passed": state.get("strategies_passed_expanded", 0),
            })

            state["active"] = False
            state["expansion_strength"] = 0.0
            state["last_deactivated"] = datetime.now(timezone.utc).isoformat()
            state["absorbed_features"] = state.get("features_enabled", [])
            log.warning("🔬 EXPANSION DEACTIVATED — discovery recovered, strength decayed to zero")
        else:
            log.info(
                f"🔬 Expansion decaying: {old_strength:.2f} → {state['expansion_strength']:.2f}"
            )

        save_expansion_state(state)


# ─── Status Report ──────────────────────────────────────────────────────────

def validate_ready() -> tuple[bool, list[str]]:
    """
    Strict post-restart validation. Returns (ok, errors).
    All checks must pass or expansion is NOT safe to trigger.
    """
    errors = []

    # 1. Module imported (if we're here, it worked)
    # 2. State file readable and clean
    state = load_expansion_state()
    if state.get("active"):
        errors.append(f"expansion_active should be False, got True")
    if state.get("expansion_strength", 0.0) != 0.0:
        errors.append(f"expansion_strength should be 0.0, got {state.get('expansion_strength')}")

    # 3. New dimensions available — verify data files
    for asset in ["NQ", "GC", "CL"]:
        p5 = DATA_DIR / asset / "5m.parquet"
        if not p5.exists():
            errors.append(f"Missing 5m data: {p5}")

    # 4. Session windows defined
    if not SESSION_WINDOWS:
        errors.append("SESSION_WINDOWS is empty")

    # 5. Expanded params generate without error
    try:
        base = {
            "rsi_threshold": 30, "rsi_period": 14, "fast_ema": 12, "slow_ema": 50,
            "adx_threshold": 20, "volume_multiplier": 1.5, "bb_period": 20, "z_score_threshold": 2.0,
        }
        ep = expanded_random_params("mean_reversion", base)
        required_keys = ["session_filter_enabled", "atr_regime_enabled",
                         "dynamic_threshold_enabled", "max_hold_bars", "max_hold_enabled"]
        for k in required_keys:
            if k not in ep:
                errors.append(f"expanded_random_params missing key: {k}")
    except Exception as e:
        errors.append(f"expanded_random_params crashed: {e}")

    # 6. Dynamic thresholds function works
    try:
        test_params = dict(base)
        test_params["dynamic_threshold_enabled"] = 1
        test_params["dynamic_threshold_scale"] = 1.5
        scaled = apply_dynamic_thresholds(test_params)
        if scaled["rsi_threshold"] == test_params["rsi_threshold"]:
            errors.append("apply_dynamic_thresholds had no effect")
    except Exception as e:
        errors.append(f"apply_dynamic_thresholds crashed: {e}")

    ok = len(errors) == 0

    # Compute code hash for version tracing
    import hashlib
    try:
        with open(Path(__file__).resolve(), "rb") as fh:
            code_hash = hashlib.sha256(fh.read()).hexdigest()[:12]
    except Exception:
        code_hash = "unknown"

    # Write audit marker
    if ok:
        cs = _load_control_state()
        _log_expansion_event("EXPANSION_READY", {
            "validation": "PASSED",
            "checks": 6,
            "gen": cs.get("stagnation_counter", 0),
            "code_hash": code_hash,
            "modules_loaded": ["timeframes_5m", "timeframes_30m", "session_filter",
                               "atr_regime", "dynamic_thresholds", "holding_time"],
        })
        log.info("✅ EXPANSION_READY = TRUE — all validation checks passed")
    else:
        _log_expansion_event("EXPANSION_READY_FAILED", {
            "validation": "FAILED",
            "errors": errors,
        })
        log.error(f"❌ EXPANSION_READY = FALSE — {len(errors)} checks failed: {errors}")

    return ok, errors


def status_report() -> str:
    """Human-readable status for logging/Discord."""
    state = load_expansion_state()
    cs = _load_control_state()
    stagnation = cs.get("stagnation_counter", 0)
    distance = max(0, STAGNATION_TRIGGER - stagnation)

    if state.get("active"):
        stats = get_expansion_stats()
        strength = state.get("expansion_strength", 0.0)
        signal = stats["signal_strength"]
        signal_emoji = {"STRONG": "🟢", "MODERATE": "🔵", "WEAK": "🟡", "EXHAUSTED": "🔴", "WATCHING": "⚪"}.get(signal, "⚪")
        surviving = stats["surviving_lineage_count"]
        gens_active = stats["gens_since_activation"]
        cross = "✅" if stats.get("cross_style_diversity") else "❌"
        tts = stats.get("time_to_survival")
        tts_str = f"{tts} gens" if tts else "N/A"
        lineage_line = ""
        if stats["new_lineage_count"] > 0:
            top = sorted(stats["new_lineages"], key=lambda x: x["best"], reverse=True)[:3]
            names = ", ".join(
                f"{l['id']}({l['best']:.2f}, x{l['survival_depth']}"
                f"{' 🔥' if l['momentum'] > 0 else ''}"
                f"{'⚠️' if not l['quality_pass'] else ''})"
                for l in top
            )
            styles = ", ".join(stats.get("surviving_styles", []))
            lineage_line = (
                f"\n🧬 LINEAGES: {stats['new_lineage_count']} new, {surviving} surviving "
                f"| {signal_emoji} {signal} ({gens_active} gens)"
                f"\n   Cross-style: {cross} [{styles or 'none'}] | T2S: {tts_str}"
                f"\n   Top: {names}"
            )
        else:
            lineage_line = f"\n🧬 LINEAGES: 0 new | {signal_emoji} {signal} ({gens_active} gens)"
        return (
            f"🔬 EXPANSION ACTIVE since gen {stats['activated_generation']}\n"
            f"Strength: {strength:.0%} (max {EXPANSION_STRENGTH_MAX:.0%})\n"
            f"Features: {', '.join(stats['features'])}\n"
            f"Expanded tested: {stats['tested']} | passed: {stats['passed']} "
            f"(rate: {stats['pass_rate']:.2%})"
            f"{lineage_line}"
        )
    else:
        return (
            f"🔬 EXPANSION STANDBY\n"
            f"Stagnation: {stagnation}/{STAGNATION_TRIGGER} "
            f"({distance} gens to trigger)\n"
            f"Discovery rate: {cs.get('last_discovery_rates', [0])[-1] if cs.get('last_discovery_rates') else 'N/A'}"
        )
