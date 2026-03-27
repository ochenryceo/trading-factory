"""Pydantic v2 response schemas for the API."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class StrategyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    strategy_code: str
    name: str
    style: str
    asset: str
    status: str
    current_stage: str
    current_mode: str | None = None
    created_at: datetime
    updated_at: datetime
    retired_at: datetime | None = None
    consecutive_demotions: int = 0
    current_rank: int | None = None
    is_active: bool = True
    template_config: dict[str, Any] | None = None


class StrategyWithMetrics(StrategyResponse):
    latest_pnl: float | None = None
    latest_sharpe: float | None = None
    latest_drawdown: float | None = None
    latest_win_rate: float | None = None
    latest_trade_count: int | None = None


class MetricResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    strategy_id: uuid.UUID
    stage: str
    pnl: float
    sharpe: float
    drawdown: float
    win_rate: float
    trade_count: int
    expectancy: float
    profit_factor: float
    timestamp: datetime


class HistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    strategy_id: uuid.UUID
    event_type: str
    from_stage: str | None = None
    to_stage: str | None = None
    reason: str | None = None
    actor: str
    created_at: datetime


class AuditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    strategy_id: uuid.UUID | None = None
    event_type: str
    source_service: str
    payload_json: dict[str, Any] | None = None
    success: bool
    created_at: datetime


class TradeExplanationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    strategy_id: uuid.UUID
    trade_id: str
    explanation_text: str
    contributing_factors_json: dict[str, Any] | None = None
    result: str
    pnl: float
    created_at: datetime


class ResearchSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    strategy_style: str
    trader_name: str
    market_focus: str
    activity_status: str
    research_notes: str | None = None
    extracted_patterns_json: dict[str, Any] | None = None
    created_at: datetime


class OverrideResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    strategy_id: uuid.UUID | None = None
    requested_by: str
    approved_by: str | None = None
    result: str
    reason: str
    created_at: datetime


class PipelineGroup(BaseModel):
    stage: str
    strategies: list[StrategyWithMetrics]
    count: int


class MetricsSummary(BaseModel):
    total_strategies: int
    active_strategies: int
    killed_strategies: int
    retired_strategies: int
    total_pnl: float
    avg_sharpe: float
    avg_win_rate: float
    strategies_by_stage: dict[str, int]
    strategies_by_style: dict[str, int]


class RiskStateResponse(BaseModel):
    mode: str
    daily_loss: float
    total_drawdown: float
    active_positions: int
    capital_at_risk: float
    kill_switches_triggered: list[str]
    strategies_under_warning: int


class KillFeedEvent(BaseModel):
    id: uuid.UUID
    strategy_id: uuid.UUID | None = None
    strategy_code: str | None = None
    event_type: str
    source_service: str
    payload_json: dict[str, Any] | None = None
    created_at: datetime


class LiveOpsResponse(BaseModel):
    active_signals: list[dict[str, Any]]
    recent_trades: list[TradeExplanationResponse]
    current_mode: str
    strategies_in_paper: int
    strategies_in_micro: int
    strategies_in_full: int
