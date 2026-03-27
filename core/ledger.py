"""Promotion Ledger — immutable records of every stage transition.

The ledger is stored in strategy_history and audit_log. This module
provides the high-level API for recording and querying promotions.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.audit import log_event
from core.enums import EventType, PipelineStage
from core.models import Strategy, StrategyHistory


async def record_promotion(
    session: AsyncSession,
    strategy: Strategy,
    from_stage: PipelineStage,
    to_stage: PipelineStage,
    actor: str,
    reason: str,
    metrics: dict[str, Any] | None = None,
) -> StrategyHistory:
    """Record an immutable promotion ledger entry."""
    entry = StrategyHistory(
        strategy_id=strategy.id,
        event_type=EventType.STAGE_PROMOTED.value,
        from_stage=from_stage.value,
        to_stage=to_stage.value,
        reason=reason,
        actor=actor,
    )
    session.add(entry)

    # Also write to audit log with full metrics payload
    await log_event(
        session,
        EventType.STAGE_PROMOTED,
        source_service=actor,
        strategy_id=strategy.id,
        payload={
            "from_stage": from_stage.value,
            "to_stage": to_stage.value,
            "reason": reason,
            "metrics": metrics or {},
        },
    )
    await session.flush()
    return entry


async def record_demotion(
    session: AsyncSession,
    strategy: Strategy,
    from_stage: PipelineStage,
    to_stage: PipelineStage,
    actor: str,
    reason: str,
    event_type: EventType = EventType.STRATEGY_DEMOTED,
) -> StrategyHistory:
    """Record an immutable demotion/kill/retirement ledger entry."""
    entry = StrategyHistory(
        strategy_id=strategy.id,
        event_type=event_type.value,
        from_stage=from_stage.value,
        to_stage=to_stage.value,
        reason=reason,
        actor=actor,
    )
    session.add(entry)

    await log_event(
        session,
        event_type,
        source_service=actor,
        strategy_id=strategy.id,
        payload={
            "from_stage": from_stage.value,
            "to_stage": to_stage.value,
            "reason": reason,
        },
    )
    await session.flush()
    return entry


async def get_ledger(
    session: AsyncSession, strategy_id: uuid.UUID
) -> list[StrategyHistory]:
    """Retrieve full promotion ledger for a strategy."""
    result = await session.execute(
        select(StrategyHistory)
        .where(StrategyHistory.strategy_id == strategy_id)
        .order_by(StrategyHistory.created_at)
    )
    return list(result.scalars().all())
