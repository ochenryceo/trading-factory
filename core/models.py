"""SQLAlchemy 2.0 models for all 8 Trading Factory tables."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all models."""
    pass


class Strategy(Base):
    """One row per strategy — core identity and lifecycle state."""
    __tablename__ = "strategies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    strategy_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    style: Mapped[str] = mapped_column(String(32), nullable=False)
    asset: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    current_stage: Mapped[str] = mapped_column(String(24), nullable=False, default="IDEA")
    current_mode: Mapped[str] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_demotions: Mapped[int] = mapped_column(Integer, default=0)
    current_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Strategy DNA — template config stored as JSON
    template_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Relationships
    metrics: Mapped[list[StrategyMetric]] = relationship(back_populates="strategy", lazy="selectin")
    history: Mapped[list[StrategyHistory]] = relationship(back_populates="strategy", lazy="selectin")
    trade_explanations: Mapped[list[TradeExplanation]] = relationship(back_populates="strategy", lazy="selectin")
    research_links: Mapped[list[StrategyResearchLink]] = relationship(back_populates="strategy", lazy="selectin")


class StrategyMetric(Base):
    """Performance metrics per strategy, stage, and date."""
    __tablename__ = "strategy_metrics"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(24), nullable=False)
    pnl: Mapped[float] = mapped_column(Float, default=0.0)
    sharpe: Mapped[float] = mapped_column(Float, default=0.0)
    drawdown: Mapped[float] = mapped_column(Float, default=0.0)
    win_rate: Mapped[float] = mapped_column(Float, default=0.0)
    trade_count: Mapped[int] = mapped_column(Integer, default=0)
    expectancy: Mapped[float] = mapped_column(Float, default=0.0)
    profit_factor: Mapped[float] = mapped_column(Float, default=0.0)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    strategy: Mapped[Strategy] = relationship(back_populates="metrics")


class StrategyHistory(Base):
    """Stage transitions and lifecycle events — immutable audit trail."""
    __tablename__ = "strategy_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    from_stage: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_stage: Mapped[str | None] = mapped_column(String(24), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    strategy: Mapped[Strategy] = relationship(back_populates="history")


class AuditLog(Base):
    """Every system event — immutable."""
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    strategy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategies.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_service: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TradeExplanation(Base):
    """Why trades happened and why they won or lost."""
    __tablename__ = "trade_explanations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False
    )
    trade_id: Mapped[str] = mapped_column(String(64), nullable=False)
    explanation_text: Mapped[str] = mapped_column(Text, nullable=False)
    contributing_factors_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    pnl: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    strategy: Mapped[Strategy] = relationship(back_populates="trade_explanations")


class ResearchSource(Base):
    """Trader inspiration and extracted influence."""
    __tablename__ = "research_sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    strategy_style: Mapped[str] = mapped_column(String(32), nullable=False)
    trader_name: Mapped[str] = mapped_column(String(128), nullable=False)
    market_focus: Mapped[str] = mapped_column(String(64), nullable=False)
    activity_status: Mapped[str] = mapped_column(String(16), default="active")
    research_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_patterns_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    strategy_links: Mapped[list[StrategyResearchLink]] = relationship(back_populates="research_source")


class StrategyResearchLink(Base):
    """Links a strategy to its research inspiration source."""
    __tablename__ = "strategy_research_links"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False
    )
    research_source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("research_sources.id", ondelete="CASCADE"), nullable=False
    )
    influence_weight: Mapped[float] = mapped_column(Float, default=1.0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    strategy: Mapped[Strategy] = relationship(back_populates="research_links")
    research_source: Mapped[ResearchSource] = relationship(back_populates="strategy_links")


class Override(Base):
    """Override attempts and approved overrides."""
    __tablename__ = "overrides"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    strategy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategies.id", ondelete="SET NULL"), nullable=True
    )
    requested_by: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
