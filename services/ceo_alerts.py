"""
CEO Alert System — Executive Status Reports
=============================================
Answers one question: "Is the system progressing toward making money — or stuck?"

Two modes:
  1. Scheduled reports: 4x daily, scattered through the day
  2. Event-triggered alerts: fire on meaningful state changes only

Design principle: Alerts explain the system, not just report it.
Silence = success. Noise = failure.

Author: Henry (autonomous build)
Date: 2026-03-26
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("ceo_alerts")

BASE_DIR = Path("Path(__file__).resolve().parents[1]")
DATA_DIR = BASE_DIR / "data"


# ─── Phase Detection ───────────────────────────────────────────────────────

def _detect_phase() -> dict:
    """
    Detect current system phase from state files.
    Returns phase info dict.
    """
    # Load all state files
    cs = _load_json(DATA_DIR / "control_state.json")
    bs = _load_json(DATA_DIR / "backtester_v2_state.json")
    es = _load_json(DATA_DIR / "expansion_state.json")
    ps = _load_json(DATA_DIR / "promotion_state.json")
    gs = _load_json(DATA_DIR / "production_gate_state.json")
    ds = _load_json(DATA_DIR / "diversity_stabilizer_state.json")

    stagnation = cs.get("stagnation_counter", 0)
    generation = bs.get("generation", 0)
    total_tested = bs.get("total_strategies_tested", 0)
    total_passed = bs.get("total_passed", 0)
    discovery_rates = cs.get("last_discovery_rates", [])
    discovery_rate = discovery_rates[-1] if discovery_rates else 0

    expansion_active = es.get("active", False)
    expansion_strength = es.get("expansion_strength", 0.0)

    promoted = ps.get("promoted", {})
    pending_reval = ps.get("pending_revalidation", {})
    cooldown_until = ps.get("data_cooldown_until_gen", 0)

    approved = gs.get("approved", {})
    watchlist = gs.get("watchlist", {})
    total_gate_evaluated = gs.get("total_evaluated", 0)

    # Determine phase
    if approved:
        phase = "PRODUCTION_READY"
        emoji = "💰"
        summary = "Strategy passed full validation. Ready for paper trading."
    elif promoted:
        phase = "PROMOTION_ACTIVE"
        emoji = "🏆"
        top_lineage = max(promoted.items(), key=lambda x: x[1].get("current_best_fitness", 0))
        summary = f"Lineage {top_lineage[0]} under focused refinement (fitness={top_lineage[1].get('current_best_fitness', 0):.3f})."
    elif expansion_active:
        phase = "EXPANSION_ACTIVE"
        emoji = "🚀"
        summary = f"New search dimensions open. Strength at {expansion_strength:.0%}."
    elif stagnation >= 400:
        phase = "PRE_EXPANSION"
        emoji = "⏳"
        remaining = 500 - stagnation
        summary = f"Search space nearly exhausted. Expansion in ~{remaining} gens."
    elif stagnation >= 200:
        phase = "LATE_EXPLORATION"
        emoji = "🔍"
        summary = "Deep exploration phase. Discovery rate declining."
    else:
        phase = "EXPLORATION"
        emoji = "🌱"
        summary = "Active exploration. System searching for edge."

    # Progression speed — estimate from discovery_rate log timestamps
    import os
    gens_per_hour = 50  # default estimate
    try:
        dr_file = DATA_DIR / "discovery_rate.jsonl"
        if dr_file.exists():
            with open(dr_file) as f:
                lines = f.readlines()
            if len(lines) >= 20:
                first = json.loads(lines[-20].strip())
                last = json.loads(lines[-1].strip())
                gen_diff = last.get("generation", 0) - first.get("generation", 0)
                t1 = datetime.fromisoformat(first.get("timestamp", "2026-01-01T00:00:00+00:00"))
                t2 = datetime.fromisoformat(last.get("timestamp", "2026-01-01T00:00:00+00:00"))
                hours_diff = max(0.1, (t2 - t1).total_seconds() / 3600)
                if gen_diff > 0:
                    gens_per_hour = gen_diff / hours_diff
    except Exception:
        pass

    # ETA to next milestone
    if not expansion_active and stagnation < 500:
        gens_to_expansion = 500 - stagnation
        eta_hours = gens_to_expansion / max(gens_per_hour, 1)
    else:
        gens_to_expansion = 0
        eta_hours = 0

    # System health confidence
    health_issues = []
    health_score = 100
    if cs.get("last_action") in ("hard_rebalance",):
        health_issues.append("hard rebalance active")
        health_score -= 15
    if discovery_rates and all(r == 0 for r in discovery_rates[-10:]) and stagnation > 400:
        health_issues.append("deep stagnation")
        health_score -= 10
    if not (DATA_DIR / "backtester_v2_state.json").exists():
        health_issues.append("backtester state missing")
        health_score -= 30
    # Check if backtester is actually running
    try:
        import subprocess
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "continuous-backtester-v2.service"],
            capture_output=True, text=True, timeout=5,
        )
        if result.stdout.strip() != "active":
            health_issues.append("backtester not running")
            health_score -= 40
    except Exception:
        pass

    health_score = max(0, min(100, health_score))
    if health_score >= 85:
        health_emoji = "🟢"
        health_label = "Healthy"
    elif health_score >= 60:
        health_emoji = "🟡"
        health_label = "Degraded"
    else:
        health_emoji = "🔴"
        health_label = "Critical"

    # Risk level
    risk_issues = []
    if stagnation > 450 and not expansion_active:
        risk_issues.append("approaching expansion without restart")
    if health_score < 60:
        risk_issues.append("system health critical")
    risk_level = "🟢 LOW" if not risk_issues else ("🟡 MEDIUM" if len(risk_issues) == 1 else "🔴 HIGH")

    return {
        "phase": phase,
        "emoji": emoji,
        "summary": summary,
        "generation": generation,
        "stagnation": stagnation,
        "total_tested": total_tested,
        "total_passed": total_passed,
        "discovery_rate": discovery_rate,
        "expansion_active": expansion_active,
        "expansion_strength": expansion_strength,
        "promoted_count": len(promoted),
        "promoted": promoted,
        "approved_count": len(approved),
        "approved": approved,
        "watchlist_count": len(watchlist),
        "gate_evaluated": total_gate_evaluated,
        "pending_revalidation": pending_reval,
        "cooldown_until": cooldown_until,
        "diversity_state": ds.get("last_state", "?"),
        "control_action": cs.get("last_action", "?"),
        "gens_per_hour": round(gens_per_hour, 1),
        "eta_hours": round(eta_hours, 1),
        "gens_to_expansion": gens_to_expansion,
        "health_score": health_score,
        "health_emoji": health_emoji,
        "health_label": health_label,
        "health_issues": health_issues,
        "risk_level": risk_level,
        "risk_issues": risk_issues,
    }


def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


# ─── Interpretation Engine ──────────────────────────────────────────────────

def _interpret(phase_data: dict) -> str:
    """Generate human interpretation of current state."""
    phase = phase_data["phase"]
    stag = phase_data["stagnation"]

    if phase == "EXPLORATION":
        return "System is actively exploring parameter space. Normal operation."

    elif phase == "LATE_EXPLORATION":
        return (
            f"System is in late-stage exploration. Stagnation at {stag} indicates "
            f"diminishing returns in current search space. This is expected pressure "
            f"building toward expansion. No intervention required."
        )

    elif phase == "PRE_EXPANSION":
        remaining = 500 - stag
        return (
            f"Search space nearly exhausted (stagnation {stag}/500). "
            f"Expansion will activate in ~{remaining} generations. "
            f"This is a pressure phase — the system is being forced to find "
            f"new dimensions. Everything is on track."
        )

    elif phase == "EXPANSION_ACTIVE":
        strength = phase_data["expansion_strength"]
        return (
            f"New search dimensions activated. {strength:.0%} of batch exploring "
            f"new timeframes, session filters, volatility regimes. "
            f"Watch for new lineage emergence — that's the key signal."
        )

    elif phase == "PROMOTION_ACTIVE":
        promoted = phase_data["promoted"]
        if promoted:
            top_lid, top_data = max(promoted.items(), key=lambda x: x[1].get("current_best_fitness", 0))
            imp = top_data.get("improvement_rate", 0)
            stab = top_data.get("stability_score", 0)
            imp_word = "improving" if imp > 0.01 else ("plateauing" if imp > -0.01 else "declining")
            return (
                f"High-confidence lineage {top_lid} under focused refinement. "
                f"Fitness {imp_word} (rate={imp:+.3f}), stability={stab:.2f}. "
                f"System is optimizing toward production readiness."
            )
        return "Promotion active but no lineage details available."

    elif phase == "PRODUCTION_READY":
        return (
            "First strategy has passed the full 10-check production gate. "
            "Ready for paper trading deployment. This is the milestone."
        )

    return "System operating normally."


def _pipeline_status(phase_data: dict) -> str:
    """Show activation state of each pipeline stage."""
    exp = phase_data.get("expansion_active", False)
    exp_str = phase_data.get("expansion_strength", 0)
    promo = phase_data.get("promoted_count", 0)
    approved = phase_data.get("approved_count", 0)
    watchlist = phase_data.get("watchlist_count", 0)
    gate_eval = phase_data.get("gate_evaluated", 0)

    lines = []
    if exp:
        lines.append(f"  Expansion: 🟢 ACTIVE ({exp_str:.0%} strength)")
    else:
        lines.append(f"  Expansion: ⏳ STANDBY")

    if promo > 0:
        lines.append(f"  Promotion: 🟢 ACTIVE ({promo} lineage{'s' if promo > 1 else ''})")
    else:
        lines.append(f"  Promotion: ⏳ INACTIVE")

    if approved > 0:
        lines.append(f"  Production Gate: ✅ {approved} APPROVED")
    elif gate_eval > 0:
        lines.append(f"  Production Gate: 🟡 {gate_eval} evaluated, {watchlist} watchlisted")
    else:
        lines.append(f"  Production Gate: ⏳ WAITING")

    return "\n".join(lines)


def _what_changes_next(phase_data: dict) -> str:
    """Explain what the next milestone unlocks and why it matters."""
    phase = phase_data["phase"]

    if phase in ("EXPLORATION", "LATE_EXPLORATION", "PRE_EXPANSION"):
        return (
            "Expansion unlocks:\n"
            "  → New timeframes (5m, 30m)\n"
            "  → Session filters (London/NY/Asia open bias)\n"
            "  → ATR regime gating + dynamic thresholds\n"
            "  → Holding time flexibility\n"
            "\n"
            "This enables first lineage formation → activates promotion + production pipeline."
        )
    elif phase == "EXPANSION_ACTIVE":
        return (
            "STRONG lineage signal unlocks:\n"
            "  → Focused evolution mode (±3-5% precision mutations)\n"
            "  → 25% compute dedicated to proven family\n"
            "  → Production Gate evaluation path opens\n"
            "\n"
            "This is the transition from discovery → refinement."
        )
    elif phase == "PROMOTION_ACTIVE":
        return (
            "Production Gate approval unlocks:\n"
            "  → Paper trading deployment\n"
            "  → 30-day live observation period\n"
            "  → GO/NO-GO for real capital\n"
            "\n"
            "This is the transition from refinement → deployment."
        )
    elif phase == "PRODUCTION_READY":
        return (
            "Paper trading success unlocks:\n"
            "  → Real capital deployment\n"
            "  → Live drift monitoring active\n"
            "  → Prop account tracking\n"
            "\n"
            "This is the transition from testing → trading."
        )
    return ""


def _calibrate_expectation(phase_data: dict) -> str:
    """Set expectations correctly — prevent doubt and overthinking."""
    phase = phase_data["phase"]

    if phase in ("EXPLORATION", "LATE_EXPLORATION"):
        return (
            "Discovery rate = 0.0% is NORMAL in this phase.\n"
            "No valid strategies expected before expansion.\n"
            "System is correctly exhausting current search space."
        )
    elif phase == "PRE_EXPANSION":
        return (
            "Discovery rate = 0.0% is EXPECTED.\n"
            "System has proven current space is exhausted.\n"
            "Expansion will unlock new dimensions — that's when discovery resumes."
        )
    elif phase == "EXPANSION_ACTIVE":
        return (
            "First 20-50 gens: new strategy types appear, near-miss diversity improves.\n"
            "50-150 gens: Sharpe recovers, trade counts stabilize, first new lineage emerges.\n"
            "Do NOT expect production candidates during expansion — this is discovery phase."
        )
    elif phase == "PROMOTION_ACTIVE":
        return (
            "Promoted lineage is under focused refinement.\n"
            "Fitness should trend upward. Stability should hold above 0.90.\n"
            "Production Gate evaluation expected within 30-50 gens of promotion."
        )
    elif phase == "PRODUCTION_READY":
        return (
            "Strategy has passed all 10 validation checks.\n"
            "Paper trading is the final human-supervised validation step.\n"
            "30-day observation period before any real capital decision."
        )
    return "System operating within expected parameters."


def _next_milestone(phase_data: dict) -> str:
    """What's the next meaningful event."""
    phase = phase_data["phase"]
    stag = phase_data["stagnation"]

    eta = phase_data.get("eta_hours", 0)
    eta_str = f" (~{eta:.0f}h)" if eta > 0 else ""

    milestones = {
        "EXPLORATION": f"⏳ Late exploration phase (~{max(0, 200 - stag)} gens)",
        "LATE_EXPLORATION": (
            f"⏳ Pre-expansion restart (~{max(0, 400 - stag)} gens)\n"
            f"  → Backtester restarts with expansion code loaded"
        ),
        "PRE_EXPANSION": (
            f"🚀 **EXPANSION TRIGGER** (~{max(0, 500 - stag)} gens{eta_str}) — CRITICAL PHASE SHIFT\n"
            f"  → Unlocks new search dimensions (5m, 30m, session filters, ATR regimes)\n"
            f"  → Enables lineage formation\n"
            f"  → Activates full system pipeline"
        ),
        "EXPANSION_ACTIVE": (
            f"🧬 **STRONG LINEAGE** — the key signal\n"
            f"  → 2+ surviving lineages across different styles\n"
            f"  → Proves expansion found real new pathways\n"
            f"  → Triggers promotion (focused evolution mode)"
        ),
        "PROMOTION_ACTIVE": (
            f"🧪 **PRODUCTION GATE** — 10-check validation\n"
            f"  → Performance, MC, Walk-Forward, Prop Simulation\n"
            f"  → If it passes: first deployable strategy"
        ),
        "PRODUCTION_READY": (
            f"📊 **PAPER TRADING DEPLOYMENT**\n"
            f"  → 30-day live observation\n"
            f"  → GO/NO-GO for real capital"
        ),
    }
    return milestones.get(phase, "Unknown")


def _action_required(phase_data: dict) -> str:
    """What should the CEO do."""
    phase = phase_data["phase"]

    if phase == "PRODUCTION_READY":
        return "Begin paper trading monitoring. Prepare NinjaScript export."
    elif phase == "PROMOTION_ACTIVE":
        return "Observe — no intervention. System refining autonomously."
    else:
        return "None — system behaving as designed."


# ─── Report Generator ──────────────────────────────────────────────────────

def generate_ceo_report() -> str:
    """
    Generate full CEO status report.
    Answers: "Is the system progressing toward making money — or stuck?"
    """
    pd = _detect_phase()

    # Key signals section
    signals = []
    signals.append(f"Gen: {pd['generation']} | Tested: {pd['total_tested']:,} | Passed: {pd['total_passed']}")
    signals.append(f"Stagnation: {pd['stagnation']}/500")
    signals.append(f"Discovery Rate: {pd['discovery_rate']:.1%}")
    signals.append(f"Diversity: {pd['diversity_state'].replace('_', ' ').title()}")
    signals.append(f"Control: {pd['control_action']}")

    if pd["expansion_active"]:
        signals.append(f"Expansion: {pd['expansion_strength']:.0%} strength")

    if pd["promoted_count"] > 0:
        for lid, pdata in pd["promoted"].items():
            fitness = pdata.get("current_best_fitness", 0)
            imp = pdata.get("improvement_rate", 0)
            stab = pdata.get("stability_score", 0)
            imp_arrow = "📈" if imp > 0.01 else ("📉" if imp < -0.01 else "➡️")
            signals.append(f"Promoted: {lid} fitness={fitness:.3f} {imp_arrow} stab={stab:.2f}")

    if pd["approved_count"] > 0:
        for sid in pd["approved"]:
            signals.append(f"✅ APPROVED: {sid}")

    if pd["watchlist_count"] > 0:
        signals.append(f"Watchlist: {pd['watchlist_count']} strategies")

    if pd["pending_revalidation"]:
        for lid, rdata in pd["pending_revalidation"].items():
            streak = rdata.get("strong_streak", 0)
            signals.append(f"🧬 Revalidation: {lid} streak={streak}/12")

    signals_str = "\n".join(f"  {s}" for s in signals)

    # Velocity section — two-step sequence: restart @ 400, expansion @ 500
    gph = pd['gens_per_hour']
    velocity = f"  Speed: ~{gph:.0f} gens/hour"
    if not pd["expansion_active"] and pd["stagnation"] < 500:
        gens_to_restart = max(0, 400 - pd["stagnation"])
        gens_to_trigger = max(0, 500 - pd["stagnation"])
        if gens_to_restart > 0:
            velocity += f"\n  ETA to restart: ~{gens_to_restart / max(gph, 1):.1f}h ({gens_to_restart} gens)"
            velocity += f"\n  ETA to expansion trigger: ~{gens_to_trigger / max(gph, 1):.1f}h ({gens_to_trigger} gens)"
            velocity += f"\n  State: **PREPARING** → READY → ACTIVE"
        elif gens_to_trigger > 0:
            velocity += f"\n  ETA to expansion trigger: ~{gens_to_trigger / max(gph, 1):.1f}h ({gens_to_trigger} gens)"
            velocity += f"\n  State: PREPARING → **READY** → ACTIVE"
    elif pd["expansion_active"]:
        velocity += f"\n  State: PREPARING → READY → **ACTIVE**"

    # State confidence — how certain is the system about its own state?
    confidence = 100
    conf_issues = []
    try:
        exp_state = _load_json(DATA_DIR / "expansion_state.json")
        ctrl = _load_json(DATA_DIR / "control_state.json")
        bt_state = _load_json(DATA_DIR / "backtester_v2_state.json")

        # Backtester state stale? (not updated in 10+ min)
        import os
        bt_path = DATA_DIR / "backtester_v2_state.json"
        if bt_path.exists():
            age_sec = datetime.now(timezone.utc).timestamp() - os.path.getmtime(str(bt_path))
            if age_sec > 600:
                confidence -= 20
                conf_issues.append("backtester state stale")

        # Expansion state mismatch (active but no features)
        if exp_state.get("active") and not exp_state.get("features_enabled"):
            confidence -= 25
            conf_issues.append("expansion active but no features")

        # Expansion should be active but isn't (stagnation > 500 but not active)
        if ctrl.get("stagnation_counter", 0) >= 500 and not exp_state.get("active"):
            confidence -= 30
            conf_issues.append("expansion should be active")

        # READY marker check after restart zone
        if 400 <= ctrl.get("stagnation_counter", 0) < 500:
            log_file = DATA_DIR / "expansion_log.jsonl"
            has_ready = False
            if log_file.exists():
                with open(log_file) as f:
                    for line in f:
                        if '"EXPANSION_READY"' in line:
                            has_ready = True
                            break
            if not has_ready:
                confidence -= 15
                conf_issues.append("EXPANSION_READY not confirmed")
    except Exception:
        pass

    confidence = max(0, min(100, confidence))
    if confidence >= 90:
        conf_band = "🟢 TRUSTED"
    elif confidence >= 70:
        conf_band = "🟡 DEGRADED"
    else:
        conf_band = "🔴 CRITICAL"
    velocity += f"\n  State Confidence: {conf_band} ({confidence}%)"
    if conf_issues:
        velocity += f" — {', '.join(conf_issues)}"

    # Expectation calibration
    expectation = _calibrate_expectation(pd)

    report = (
        f"**🧠 SYSTEM STATUS — CEO UPDATE**\n"
        f"\n"
        f"**Phase:** {pd['emoji']} {pd['phase'].replace('_', ' ').title()}\n"
        f"**Health:** {pd['health_emoji']} {pd['health_score']}% ({pd['health_label']})"
        f"{' — ' + ', '.join(pd['health_issues']) if pd['health_issues'] else ''}\n"
        f"**Risk:** {pd['risk_level']}"
        f"{' — ' + ', '.join(pd['risk_issues']) if pd['risk_issues'] else ''}\n"
        f"\n"
        f"**Summary:**\n"
        f"{pd['summary']}\n"
        f"\n"
        f"**Key Signals:**\n"
        f"{signals_str}\n"
        f"\n"
        f"**Progression:**\n"
        f"{velocity}\n"
        f"\n"
        f"**Expectation:**\n"
        f"{expectation}\n"
        f"\n"
        f"**Pipeline:**\n"
        f"{_pipeline_status(pd)}\n"
        f"\n"
        f"**Interpretation:**\n"
        f"{_interpret(pd)}\n"
        f"\n"
        f"**Next Milestone:**\n"
        f"{_next_milestone(pd)}\n"
        f"\n"
        f"**What Changes Next:**\n"
        f"{_what_changes_next(pd)}\n"
        f"\n"
        f"**Action:**\n"
        f"{_action_required(pd)}"
    )

    return report
