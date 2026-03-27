"""Automatic kill switch enforcement — checks and acts."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.audit import log_event
from core.enums import EventType, SystemMode
from core.tracker import kill_strategy
from services.risk.rules import (
    KillRule,
    check_strategy_kill,
    check_system_kill,
)


@dataclass
class KillSwitchResult:
    """Result of a kill-switch evaluation."""
    triggered: bool
    rules_fired: list[KillRule]
    action_taken: str


async def enforce_strategy_kill_switch(
    session: AsyncSession,
    strategy_id: uuid.UUID,
    metrics: dict[str, Any],
) -> KillSwitchResult:
    """Evaluate strategy metrics against kill rules and auto-kill if triggered."""
    fired = check_strategy_kill(metrics)
    if not fired:
        return KillSwitchResult(triggered=False, rules_fired=[], action_taken="none")

    reasons = [f"{r.name}: {r.description}" for r in fired]
    reason_str = "; ".join(reasons)

    await kill_strategy(
        session,
        strategy_id,
        actor="RiskEngine",
        reason=reason_str,
    )

    await log_event(
        session,
        EventType.RISK_LIMIT_HIT,
        source_service="RiskEngine",
        strategy_id=strategy_id,
        payload={"rules_fired": reasons, "metrics": metrics},
    )

    return KillSwitchResult(
        triggered=True,
        rules_fired=fired,
        action_taken=f"Strategy killed: {reason_str}",
    )


@dataclass
class SystemRiskState:
    """Current global risk posture."""
    mode: SystemMode
    daily_loss: float
    total_drawdown: float
    active_positions: int
    capital_at_risk: float
    kill_switches_triggered: list[str]
    strategies_under_warning: int


# In-memory global state (in production, backed by Redis)
_system_state: dict[str, Any] = {
    "daily_loss": 0.0,
    "total_drawdown": 0.0,
    "correlated_positions": 0,
    "data_staleness_seconds": 0,
    "active_positions": 0,
    "capital_at_risk": 0.0,
    "strategies_under_warning": 0,
}


def get_system_risk_state() -> SystemRiskState:
    """Evaluate current system state against all system kill rules."""
    fired = check_system_kill(_system_state)
    if fired:
        mode = SystemMode.HALTED
    elif _system_state.get("daily_loss", 0) > 0.015:
        mode = SystemMode.CAUTION
    else:
        mode = SystemMode.NORMAL

    return SystemRiskState(
        mode=mode,
        daily_loss=_system_state.get("daily_loss", 0.0),
        total_drawdown=_system_state.get("total_drawdown", 0.0),
        active_positions=_system_state.get("active_positions", 0),
        capital_at_risk=_system_state.get("capital_at_risk", 0.0),
        kill_switches_triggered=[r.name for r in fired],
        strategies_under_warning=_system_state.get("strategies_under_warning", 0),
    )


def update_system_state(updates: dict[str, Any]) -> None:
    """Update the in-memory system state (called by monitoring loop)."""
    _system_state.update(updates)
