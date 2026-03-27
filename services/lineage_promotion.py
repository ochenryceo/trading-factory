"""
Lineage Promotion — Focused Evolution Mode
============================================
When a lineage proves itself (STRONG signal from expansion tracker),
shift compute from random exploration to precision refinement of that family.

What it does:
  - Dedicates 20-30% of batch to promoted lineage mutations
  - Tightens mutation range to ±3-5% (refinement, not exploration)
  - Preserves core structure (style, timeframe, param ranges)
  - Biases parent selection toward promoted family
  - Tracks family-level performance (not individual strategies)

Trigger:
  signal_strength == "STRONG" (2+ surviving lineages, cross-style, quality gate passed)

Safety:
  - Max 2 promoted lineages at once (prevents tunnel vision)
  - Auto-demotes if family fitness stalls for 30 gens
  - Never exceeds 30% compute allocation (70% stays exploration/random)
  - Promotion requires STRONG signal — never promotes on WEAK/single lucky hit

Integration:
  Called by generate_batch_dnas() to inject focused evolution strategies.
  Reads lineage_scores.json for family data.
  Writes promotion_state.json for persistence.

Author: Henry (autonomous build)
Date: 2026-03-26
"""

import json
import logging
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("lineage_promotion")

BASE_DIR = Path("Path(__file__).resolve().parents[1]")
PROMOTION_STATE_FILE = BASE_DIR / "data" / "promotion_state.json"
LINEAGE_FILE = BASE_DIR / "data" / "lineage_scores.json"
NEAR_MISS_FILE = BASE_DIR / "data" / "near_misses.jsonl"
PROMOTION_LOG_FILE = BASE_DIR / "data" / "promotion_log.jsonl"

# ─── Configuration ──────────────────────────────────────────────────────────

MAX_PROMOTED = 2                  # max concurrent promoted lineages
PROMOTION_BUDGET = 0.25           # 25% of batch dedicated to promoted lineages
MAX_PROMOTION_BUDGET = 0.30       # hard cap
REFINEMENT_MUTATION_LO = 0.95     # ±5% tight mutation
REFINEMENT_MUTATION_HI = 1.05
PRECISION_MUTATION_LO = 0.97      # ±3% precision mutation (deep refinement)
PRECISION_MUTATION_HI = 1.03

# Promotion criteria
MIN_SURVIVAL_DEPTH = 2            # must have 2+ offspring
MIN_BEST_FITNESS = 0.55           # quality gate
MIN_MOMENTUM = -0.05              # not actively declining

# Demotion criteria
STALL_GENS = 30                   # demote if no fitness improvement in 30 gens
FITNESS_FLOOR = 0.50              # demote if family best drops below this

# Entry buffer: STRONG signal must persist N gens before promotion
PROMOTION_ENTRY_BUFFER = 12       # must see STRONG for 12 gens before promoting

# Data change cooldown: pause promotion after data expansion
DATA_COOLDOWN_GENS = 25           # disable promotion for 25 gens after data change

# Anti-dominance: reduce budget if promoted lineages dominate passed strategies
DOMINANCE_THRESHOLD = 0.40        # if promoted > 40% of passed, reduce
DOMINANCE_REDUCTION = 0.10        # reduce budget by 10%

PARAM_RANGES = {
    "rsi_threshold": (20, 45),
    "rsi_period": (5, 21),
    "fast_ema": (8, 30),
    "slow_ema": (30, 80),
    "adx_threshold": (10, 30),
    "volume_multiplier": (1.0, 2.5),
    "bb_period": (10, 30),
    "z_score_threshold": (1.0, 3.0),
}


# ─── State Management ──────────────────────────────────────────────────────

def load_promotion_state() -> dict:
    """Load promotion state from disk."""
    if PROMOTION_STATE_FILE.exists():
        try:
            with open(PROMOTION_STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "promoted": {},        # lineage_id -> promotion data
        "total_promotions": 0,
        "total_demotions": 0,
        "strong_signal_streak": 0,  # consecutive gens with STRONG signal
        "data_cooldown_until_gen": 0,  # promotion paused until this gen
    }


def save_promotion_state(state: dict):
    """Persist promotion state."""
    PROMOTION_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PROMOTION_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _log_promotion_event(event: str, details: dict = None):
    """Append to promotion log."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **(details or {}),
    }
    PROMOTION_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PROMOTION_LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    log.info(f"🏆 PROMOTION: {event} | {details or ''}")


# ─── Lineage Data ──────────────────────────────────────────────────────────

def _load_lineages() -> dict:
    """Load lineage scores."""
    if LINEAGE_FILE.exists():
        try:
            with open(LINEAGE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _get_lineage_seeds(lineage_id: str, top_n: int = 10) -> list[dict]:
    """
    Get the best near-miss strategies from a specific lineage.
    These are the mutation parents for focused evolution.
    """
    seeds = []
    if not NEAR_MISS_FILE.exists():
        return seeds

    try:
        with open(NEAR_MISS_FILE) as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    code = entry.get("strategy_code", "")
                    parent = entry.get("parent_id", "")
                    # Match if strategy or its parent belongs to this lineage
                    if lineage_id in code or lineage_id in parent:
                        seeds.append(entry)
                except Exception:
                    continue
    except Exception:
        pass

    # Sort by Sharpe descending, take top N
    seeds.sort(key=lambda x: x.get("sharpe", 0), reverse=True)
    return seeds[:top_n]


# ─── Promotion Logic ───────────────────────────────────────────────────────

def evaluate_for_promotion(expansion_stats: dict) -> list[dict]:
    """
    Check if any lineages qualify for promotion.
    
    Requirements:
      - signal_strength == "STRONG"
      - Lineage has survival_depth >= 2
      - Best fitness >= 0.55
      - Momentum >= -0.05 (not declining)
    
    Returns list of candidates sorted by best fitness.
    """
    if expansion_stats.get("signal_strength") != "STRONG":
        return []

    candidates = []
    for lineage in expansion_stats.get("new_lineages", []):
        if (lineage.get("surviving", False)
                and lineage.get("survival_depth", 0) >= MIN_SURVIVAL_DEPTH
                and lineage.get("best", 0) >= MIN_BEST_FITNESS
                and lineage.get("momentum", -1) >= MIN_MOMENTUM):
            candidates.append(lineage)

    # Sort by best fitness descending
    candidates.sort(key=lambda x: x.get("best", 0), reverse=True)
    return candidates


def promote(generation: int, expansion_stats: dict) -> dict:
    """
    Main entry point — called each generation after expansion stats are computed.
    Evaluates candidates, promotes qualifying lineages, demotes stale ones.
    
    Entry buffer: STRONG signal must persist for PROMOTION_ENTRY_BUFFER gens
    before any promotion fires. Prevents short-lived spikes.
    """
    state = load_promotion_state()
    candidates = evaluate_for_promotion(expansion_stats)

    # ── 0: Data cooldown guard — pause after data expansion ──
    cooldown_until = state.get("data_cooldown_until_gen", 0)
    if generation < cooldown_until:
        remaining = cooldown_until - generation
        log.info(f"🧊 Promotion paused: data cooldown ({remaining} gens remaining)")
        save_promotion_state(state)
        return state

    # ── 0b: Revalidation tracker — update pending lineages ──
    pending = state.get("pending_revalidation", {})
    if pending and expansion_stats.get("signal_strength") == "STRONG":
        surviving_ids = set(
            l["id"] for l in expansion_stats.get("new_lineages", []) if l.get("surviving")
        )
        for lid, rdata in list(pending.items()):
            if lid in surviving_ids:
                rdata["strong_streak"] = rdata.get("strong_streak", 0) + 1
                if rdata["strong_streak"] >= PROMOTION_ENTRY_BUFFER:
                    rdata["status"] = "REVALIDATED"
                    _log_promotion_event("REVALIDATED", {
                        "lineage_id": lid,
                        "generation": generation,
                        "gens_to_revalidate": generation - rdata.get("demoted_at_gen", generation),
                    })
                    log.warning(f"🧬 {lid} REVALIDATED — survived data transition")
                    del pending[lid]
            else:
                rdata["strong_streak"] = 0
    # Clear any revalidated entries that are stale (100+ gens)
    for lid in list(pending.keys()):
        if generation - pending[lid].get("demoted_at_gen", generation) > 100:
            pending[lid]["status"] = "FAILED_REVALIDATION"
            _log_promotion_event("FAILED_REVALIDATION", {"lineage_id": lid, "generation": generation})
            log.info(f"🧬 {lid} failed revalidation — removed after 100 gens")
            del pending[lid]
    state["pending_revalidation"] = pending

    # ── 1: Entry buffer — track consecutive STRONG gens ──
    if expansion_stats.get("signal_strength") == "STRONG":
        state["strong_signal_streak"] = state.get("strong_signal_streak", 0) + 1
    else:
        state["strong_signal_streak"] = 0

    buffer_met = state["strong_signal_streak"] >= PROMOTION_ENTRY_BUFFER

    # ── 2: Promote new lineages (only if buffer met) ──
    current_promoted = state.get("promoted", {})

    if buffer_met and candidates:
        for candidate in candidates:
            lid = candidate["id"]

            # Skip if already promoted or at max
            if lid in current_promoted:
                continue
            if len(current_promoted) >= MAX_PROMOTED:
                break

            current_promoted[lid] = {
                "promoted_at_gen": generation,
                "promoted_at": datetime.now(timezone.utc).isoformat(),
                "style": candidate.get("style", "unknown"),
                "best_fitness_at_promotion": candidate["best"],
                "current_best_fitness": candidate["best"],
                "survival_depth": candidate["survival_depth"],
                "momentum": candidate["momentum"],
                "gens_since_improvement": 0,
                "offspring_produced": 0,
                "offspring_passed": 0,
                "fitness_history": [candidate["best"]],  # track improvement rate
            }
            state["total_promotions"] = state.get("total_promotions", 0) + 1

            _log_promotion_event("PROMOTED", {
                "lineage_id": lid,
                "generation": generation,
                "style": candidate.get("style"),
                "best_fitness": candidate["best"],
                "survival_depth": candidate["survival_depth"],
                "momentum": candidate["momentum"],
                "strong_signal_streak": state["strong_signal_streak"],
            })
            log.warning(f"🏆 LINEAGE PROMOTED: {lid} (fitness={candidate['best']:.3f}, "
                         f"style={candidate.get('style')}, depth={candidate['survival_depth']}, "
                         f"after {state['strong_signal_streak']} STRONG gens)")
    elif candidates and not buffer_met:
        log.info(f"🏆 Promotion candidates found but buffer not met "
                 f"({state['strong_signal_streak']}/{PROMOTION_ENTRY_BUFFER} STRONG gens)")

    # ── 3: Update existing promotions + track improvement rate ──
    lineages = _load_lineages()
    demote_list = []

    for lid, pdata in current_promoted.items():
        ldata = lineages.get(lid, {})
        if isinstance(ldata, dict):
            new_best = ldata.get("best", 0)

            # Track fitness history (improvement rate metric)
            fh = pdata.get("fitness_history", [])
            fh.append(new_best)
            if len(fh) > 50:
                fh = fh[-50:]  # keep last 50 snapshots
            pdata["fitness_history"] = fh

            # Compute improvement rate (last 10 vs previous 10)
            if len(fh) >= 20:
                recent = sum(fh[-10:]) / 10
                earlier = sum(fh[-20:-10]) / 10
                pdata["improvement_rate"] = round(recent - earlier, 4)
            elif len(fh) >= 4:
                half = len(fh) // 2
                recent = sum(fh[half:]) / (len(fh) - half)
                earlier = sum(fh[:half]) / half
                pdata["improvement_rate"] = round(recent - earlier, 4)
            else:
                pdata["improvement_rate"] = 0.0

            # Stability score: CV of last 5 fitness values (lower = more stable)
            if len(fh) >= 5:
                top5 = sorted(fh[-10:], reverse=True)[:5]  # best 5 from recent 10
                mean_f = sum(top5) / 5
                if mean_f > 0:
                    std_f = (sum((x - mean_f) ** 2 for x in top5) / 5) ** 0.5
                    pdata["stability_score"] = round(1.0 - min(1.0, std_f / mean_f), 3)  # 1.0 = perfectly stable
                else:
                    pdata["stability_score"] = 0.0
            else:
                pdata["stability_score"] = None  # not enough data

            if new_best > pdata.get("current_best_fitness", 0):
                pdata["current_best_fitness"] = new_best
                pdata["gens_since_improvement"] = 0
            else:
                pdata["gens_since_improvement"] = pdata.get("gens_since_improvement", 0) + 1

            # ── Demotion check ──
            if pdata["gens_since_improvement"] >= STALL_GENS:
                demote_list.append((lid, "stalled"))
            elif new_best < FITNESS_FLOOR:
                demote_list.append((lid, "fitness_floor"))

    # ── 4: Execute demotions ──
    for lid, reason in demote_list:
        pdata = current_promoted.pop(lid, {})
        state["total_demotions"] = state.get("total_demotions", 0) + 1
        _log_promotion_event("DEMOTED", {
            "lineage_id": lid,
            "reason": reason,
            "generation": generation,
            "gens_promoted": generation - pdata.get("promoted_at_gen", generation),
            "offspring_produced": pdata.get("offspring_produced", 0),
            "offspring_passed": pdata.get("offspring_passed", 0),
            "best_fitness": pdata.get("current_best_fitness", 0),
            "improvement_rate": pdata.get("improvement_rate", 0),
        })
        log.warning(f"📉 LINEAGE DEMOTED: {lid} (reason={reason})")

    # ── 5: Expansion interaction — dampen expansion when promotion active ──
    if current_promoted:
        try:
            from services.search_expansion import load_expansion_state, save_expansion_state
            exp_state = load_expansion_state()
            if exp_state.get("active") and exp_state.get("expansion_strength", 0) > 0:
                old = exp_state["expansion_strength"]
                exp_state["expansion_strength"] = round(old * 0.80, 3)  # dampen by 20%
                save_expansion_state(exp_state)
                if abs(old - exp_state["expansion_strength"]) > 0.01:
                    log.info(f"🏆↔🔬 Promotion active → expansion dampened: "
                             f"{old:.2f} → {exp_state['expansion_strength']:.2f}")
        except Exception:
            pass

    state["promoted"] = current_promoted
    save_promotion_state(state)
    return state


# ─── Batch Generation ──────────────────────────────────────────────────────

def get_promotion_budget() -> float:
    """
    Return current promotion budget (fraction of batch).
    Includes anti-dominance guard: reduces budget if promoted lineages
    dominate too much of passed strategies.
    """
    state = load_promotion_state()
    promoted = state.get("promoted", {})
    n_promoted = len(promoted)
    if n_promoted == 0:
        return 0.0

    # Base budget
    budget = min(MAX_PROMOTION_BUDGET, PROMOTION_BUDGET * n_promoted / MAX_PROMOTED)

    # Anti-dominance guard: check if promoted offspring dominate passed strategies
    total_offspring_passed = sum(
        p.get("offspring_passed", 0) for p in promoted.values()
    )
    total_offspring = sum(
        p.get("offspring_produced", 0) for p in promoted.values()
    )
    if total_offspring > 20:  # need enough data
        pass_rate = total_offspring_passed / total_offspring
        if pass_rate > DOMINANCE_THRESHOLD:
            budget = max(0.05, budget - DOMINANCE_REDUCTION)
            log.info(f"🏆 Anti-dominance: promoted pass rate {pass_rate:.0%} > "
                     f"{DOMINANCE_THRESHOLD:.0%} → budget reduced to {budget:.0%}")

    return budget


def generate_promoted_strategies(generation: int, count: int) -> list[dict]:
    """
    Generate focused evolution strategies for promoted lineages.
    
    - Finds best seeds from each promoted lineage
    - Applies tight ±3-5% mutations (refinement, not exploration)
    - Preserves core structure (style, general param region)
    - Tags with PROMO- prefix for tracking
    """
    state = load_promotion_state()
    promoted = state.get("promoted", {})

    if not promoted:
        return []

    strategies = []
    lineage_ids = list(promoted.keys())

    # Distribute count across promoted lineages (round-robin)
    per_lineage = max(1, count // len(lineage_ids))

    for lid in lineage_ids:
        pdata = promoted[lid]
        seeds = _get_lineage_seeds(lid, top_n=5)

        if not seeds:
            # No seeds found — try using lineage data directly
            lineages = _load_lineages()
            ldata = lineages.get(lid, {})
            log.warning(f"No near-miss seeds for {lid}, skipping focused evolution")
            continue

        for i in range(per_lineage):
            if len(strategies) >= count:
                break

            # Pick a seed (bias toward higher Sharpe)
            seed = random.choices(
                seeds,
                weights=[s.get("sharpe", 0.1) for s in seeds],
                k=1,
            )[0]

            # Decide mutation tightness based on promotion age
            gens_promoted = generation - pdata.get("promoted_at_gen", generation)
            if gens_promoted > 15:
                # Deep refinement — ±3%
                mut_lo, mut_hi = PRECISION_MUTATION_LO, PRECISION_MUTATION_HI
            else:
                # Early refinement — ±5%
                mut_lo, mut_hi = REFINEMENT_MUTATION_LO, REFINEMENT_MUTATION_HI

            # Mutate seed params tightly
            seed_params = seed.get("parameters", {})
            mutated = {}
            for k, (lo, hi) in PARAM_RANGES.items():
                base_val = seed_params.get(k, (lo + hi) / 2 if isinstance(lo, float) else (lo + hi) // 2)
                factor = random.uniform(mut_lo, mut_hi)
                new_val = base_val * factor
                if isinstance(lo, float):
                    mutated[k] = round(max(lo, min(hi, new_val)), 2)
                else:
                    mutated[k] = int(max(lo, min(hi, round(new_val))))

            # Preserve expansion dimensions if present in seed
            for exp_key in ["session_filter_enabled", "session_filter_start", "session_filter_end",
                            "session_name", "atr_regime_enabled", "atr_regime_period",
                            "atr_regime_percentile", "dynamic_threshold_enabled",
                            "dynamic_threshold_scale", "max_hold_bars", "max_hold_enabled"]:
                if exp_key in seed_params:
                    mutated[exp_key] = seed_params[exp_key]

            seq = random.randint(10000, 99999)
            strategies.append({
                "strategy_code": f"PROMO-G{generation}-{seq}",
                "style": pdata.get("style", seed.get("style", "unknown")),
                "parameters": mutated,
                "parent_id": seed.get("strategy_code", lid),
                "lineage_id": lid,
                "promoted": True,
            })

        # Update offspring count
        pdata["offspring_produced"] = pdata.get("offspring_produced", 0) + per_lineage

    save_promotion_state(state)
    return strategies[:count]


def track_promoted_result(strategy: dict, passed: bool):
    """Track result of a promoted strategy."""
    state = load_promotion_state()
    lid = strategy.get("lineage_id", "")
    if lid in state.get("promoted", {}):
        if passed:
            state["promoted"][lid]["offspring_passed"] = (
                state["promoted"][lid].get("offspring_passed", 0) + 1
            )
        save_promotion_state(state)


# ─── Status Report ──────────────────────────────────────────────────────────

def status_report() -> str:
    """Human-readable promotion status."""
    state = load_promotion_state()
    promoted = state.get("promoted", {})

    streak = state.get("strong_signal_streak", 0)
    if not promoted:
        if streak > 0:
            return (f"🏆 PROMOTION: No active promotions "
                    f"| STRONG streak: {streak}/{PROMOTION_ENTRY_BUFFER}")
        return "🏆 PROMOTION: No active promotions"

    lines = [f"🏆 PROMOTION: {len(promoted)} active | Budget: {get_promotion_budget():.0%} "
             f"| STRONG streak: {streak}"]
    for lid, pdata in promoted.items():
        fitness = pdata.get("current_best_fitness", 0)
        style = pdata.get("style", "?")
        offspring = pdata.get("offspring_produced", 0)
        passed = pdata.get("offspring_passed", 0)
        stall = pdata.get("gens_since_improvement", 0)
        imp_rate = pdata.get("improvement_rate", 0)
        pass_rate = passed / max(offspring, 1)
        stall_warn = f" ⚠️ stall:{stall}" if stall >= 15 else ""
        stability = pdata.get("stability_score")
        stab_str = f" stab={'✅' if stability and stability >= 0.85 else '⚠️'}{stability:.2f}" if stability is not None else ""
        imp_arrow = "📈" if imp_rate > 0.01 else ("📉" if imp_rate < -0.01 else "➡️")
        lines.append(
            f"  {lid} [{style}] fitness={fitness:.3f} {imp_arrow}{imp_rate:+.3f}{stab_str} "
            f"offspring={offspring} passed={passed} ({pass_rate:.0%}){stall_warn}"
        )

    # Show pending revalidation
    pending = state.get("pending_revalidation", {})
    if pending:
        lines.append("  🧬 Pending revalidation:")
        for lid, rdata in pending.items():
            streak = rdata.get("strong_streak", 0)
            lines.append(f"    {lid} [{rdata.get('previous_style','?')}] "
                         f"streak={streak}/{PROMOTION_ENTRY_BUFFER} "
                         f"prev_fitness={rdata.get('previous_best_fitness',0):.3f}")

    return "\n".join(lines)


def get_promoted_lineage_ids() -> list[str]:
    """Return list of currently promoted lineage IDs."""
    state = load_promotion_state()
    return list(state.get("promoted", {}).keys())


def trigger_data_cooldown(current_gen: int):
    """
    Call after any data expansion. Pauses promotion for DATA_COOLDOWN_GENS
    and demotes all active lineages (they need to re-prove on new data).
    """
    state = load_promotion_state()
    state["data_cooldown_until_gen"] = current_gen + DATA_COOLDOWN_GENS
    state["strong_signal_streak"] = 0

    # Demote all — flag for re-validation on new data
    pending = state.get("pending_revalidation", {})
    for lid in list(state.get("promoted", {}).keys()):
        pdata = state["promoted"].pop(lid)
        state["total_demotions"] = state.get("total_demotions", 0) + 1
        pending[lid] = {
            "status": "NEEDS_REVALIDATION",
            "demoted_at_gen": current_gen,
            "previous_best_fitness": pdata.get("current_best_fitness", 0),
            "previous_style": pdata.get("style", "unknown"),
            "strong_streak": 0,
        }
        _log_promotion_event("DEMOTED_DATA_COOLDOWN", {
            "lineage_id": lid,
            "generation": current_gen,
            "cooldown_until": current_gen + DATA_COOLDOWN_GENS,
        })
        log.warning(f"🧊 {lid} → NEEDS_REVALIDATION (cooldown until gen {current_gen + DATA_COOLDOWN_GENS})")
    state["pending_revalidation"] = pending

    save_promotion_state(state)
    _log_promotion_event("DATA_COOLDOWN_ACTIVATED", {
        "generation": current_gen,
        "cooldown_until": current_gen + DATA_COOLDOWN_GENS,
    })
