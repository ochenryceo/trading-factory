"""Pipeline state machine — hard gate enforcement, no stage skipping."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.enums import EventType, PipelineStage, STAGE_ORDER, StrategyStatus


# --------------------------------------------------------------------------- #
# Gate definitions: what metrics must be met to leave each stage              #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class GateRequirement:
    """Minimum metrics to pass a given stage gate."""
    min_win_rate: float | None = None
    min_sharpe: float | None = None
    max_drawdown: float | None = None
    min_trades: int | None = None
    min_duration_days: int | None = None
    regimes_required: list[str] | None = None
    degradation_axes: list[str] | None = None
    dependency_components: list[str] | None = None


STAGE_GATES: dict[PipelineStage, GateRequirement] = {
    PipelineStage.IDEA: GateRequirement(),  # must fit template + structured output
    PipelineStage.FAST_VALIDATION: GateRequirement(
        min_win_rate=0.45, min_trades=30, max_drawdown=0.12,
    ),
    PipelineStage.BACKTEST: GateRequirement(
        min_win_rate=0.40, min_sharpe=0.5, max_drawdown=0.10, min_trades=500
    ),
    PipelineStage.VALIDATION: GateRequirement(
        regimes_required=["trending", "ranging", "volatile"],
    ),
    PipelineStage.PAPER: GateRequirement(
        min_duration_days=14, min_win_rate=0.35, min_sharpe=0.3, max_drawdown=0.10,
    ),
    PipelineStage.DEGRADATION: GateRequirement(
        degradation_axes=["parameter", "execution", "data", "regime"],
    ),
    PipelineStage.DEPENDENCY: GateRequirement(
        dependency_components=["time_filter", "volume_filter", "secondary_indicator"],
    ),
    PipelineStage.MICRO_LIVE: GateRequirement(
        min_win_rate=0.35, min_sharpe=0.3, max_drawdown=0.08,
    ),
    PipelineStage.FULL_LIVE: GateRequirement(
        min_win_rate=0.35, min_sharpe=0.3, max_drawdown=0.08,
    ),
}


# --------------------------------------------------------------------------- #
# Allowed transitions                                                         #
# --------------------------------------------------------------------------- #

def _build_promotion_map() -> dict[PipelineStage, PipelineStage]:
    """Each stage can only promote to the next one in sequence."""
    m: dict[PipelineStage, PipelineStage] = {}
    for i, stage in enumerate(STAGE_ORDER[:-1]):
        m[stage] = STAGE_ORDER[i + 1]
    return m


PROMOTION_MAP: dict[PipelineStage, PipelineStage] = _build_promotion_map()

# Demotion always goes one step back (or to BACKTEST on kill-switch)
DEMOTION_MAP: dict[PipelineStage, PipelineStage] = {
    stage: STAGE_ORDER[max(i - 1, 0)]
    for i, stage in enumerate(STAGE_ORDER)
}


# --------------------------------------------------------------------------- #
# Transition engine                                                           #
# --------------------------------------------------------------------------- #

@dataclass
class TransitionResult:
    allowed: bool
    from_stage: PipelineStage
    to_stage: PipelineStage | None
    event_type: EventType | None
    reason: str
    new_status: StrategyStatus | None = None


def can_promote(
    current_stage: PipelineStage,
    metrics: dict[str, Any] | None = None,
) -> TransitionResult:
    """Check whether a strategy can be promoted from its current stage."""
    if current_stage == PipelineStage.FULL_LIVE:
        return TransitionResult(
            allowed=False,
            from_stage=current_stage,
            to_stage=None,
            event_type=None,
            reason="Already at FULL_LIVE — no further promotion.",
        )

    target = PROMOTION_MAP[current_stage]
    gate = STAGE_GATES[current_stage]
    metrics = metrics or {}

    # Validate gate requirements
    failures: list[str] = []

    if gate.min_win_rate is not None:
        wr = metrics.get("win_rate", 0)
        if wr < gate.min_win_rate:
            failures.append(f"win_rate {wr:.2f} < {gate.min_win_rate}")

    if gate.min_sharpe is not None:
        sh = metrics.get("sharpe", 0)
        if sh < gate.min_sharpe:
            failures.append(f"sharpe {sh:.2f} < {gate.min_sharpe}")

    if gate.max_drawdown is not None:
        dd = metrics.get("drawdown", 1.0)
        if dd > gate.max_drawdown:
            failures.append(f"drawdown {dd:.2f} > {gate.max_drawdown}")

    if gate.min_trades is not None:
        tc = metrics.get("trade_count", 0)
        if tc < gate.min_trades:
            failures.append(f"trade_count {tc} < {gate.min_trades}")

    if failures:
        return TransitionResult(
            allowed=False,
            from_stage=current_stage,
            to_stage=target,
            event_type=EventType.STAGE_REJECTED,
            reason=f"Gate failed: {'; '.join(failures)}",
        )

    return TransitionResult(
        allowed=True,
        from_stage=current_stage,
        to_stage=target,
        event_type=EventType.STAGE_PROMOTED,
        reason=f"Promoted {current_stage.value} → {target.value}",
    )


def demote(
    current_stage: PipelineStage,
    reason: str = "Performance degradation",
    consecutive_demotions: int = 0,
) -> TransitionResult:
    """Demote a strategy one stage back. 3 consecutive → retire."""
    if consecutive_demotions >= 2:  # this would be the 3rd
        return TransitionResult(
            allowed=True,
            from_stage=current_stage,
            to_stage=PipelineStage.IDEA,
            event_type=EventType.STRATEGY_RETIRED,
            reason=f"3 consecutive demotions — permanently retired. {reason}",
            new_status=StrategyStatus.RETIRED,
        )

    target = DEMOTION_MAP.get(current_stage, PipelineStage.IDEA)
    return TransitionResult(
        allowed=True,
        from_stage=current_stage,
        to_stage=target,
        event_type=EventType.STRATEGY_DEMOTED,
        reason=reason,
    )


def kill_switch_demote(current_stage: PipelineStage, reason: str) -> TransitionResult:
    """Kill-switch triggered → demote to BACKTEST."""
    return TransitionResult(
        allowed=True,
        from_stage=current_stage,
        to_stage=PipelineStage.BACKTEST,
        event_type=EventType.STRATEGY_KILLED,
        reason=f"Kill switch: {reason}",
        new_status=StrategyStatus.KILLED,
    )
