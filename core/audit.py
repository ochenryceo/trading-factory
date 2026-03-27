"""Audit logging — every system event is recorded immutably."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.enums import EventType
from core.models import AuditLog


async def log_event(
    session: AsyncSession,
    event_type: EventType,
    source_service: str,
    *,
    strategy_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
    success: bool = True,
) -> AuditLog:
    """Write an immutable audit log entry."""
    entry = AuditLog(
        strategy_id=strategy_id,
        event_type=event_type.value,
        source_service=source_service,
        payload_json=payload or {},
        success=success,
    )
    session.add(entry)
    await session.flush()
    return entry
