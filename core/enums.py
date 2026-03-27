"""Enumerations for the Trading Factory pipeline."""
from enum import Enum


class PipelineStage(str, Enum):
    """Strategy lifecycle stages — strict ordering, no skipping."""
    IDEA = "IDEA"
    FAST_VALIDATION = "FAST_VALIDATION"
    BACKTEST = "BACKTEST"
    VALIDATION = "VALIDATION"
    PAPER = "PAPER"
    DEGRADATION = "DEGRADATION"
    DEPENDENCY = "DEPENDENCY"
    MICRO_LIVE = "MICRO_LIVE"
    FULL_LIVE = "FULL_LIVE"


# Ordered list for index-based promotion logic
STAGE_ORDER: list[PipelineStage] = list(PipelineStage)


class StrategyStatus(str, Enum):
    """Current operational status of a strategy."""
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    KILLED = "KILLED"
    RETIRED = "RETIRED"
    PENDING = "PENDING"
    REJECTED_FAST = "REJECTED_FAST"


class StrategyStyle(str, Enum):
    """Trading style categories."""
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    SCALP = "scalp"
    TREND = "trend"
    NEWS_REACTION = "news_reaction"
    VOLUME_FLOW = "volume_flow"


class Asset(str, Enum):
    """Tradeable instruments."""
    NQ = "NQ"
    GC = "GC"
    CL = "CL"


class EventType(str, Enum):
    """All tracked system events."""
    STRATEGY_CREATED = "STRATEGY_CREATED"
    FAST_VALIDATION_STARTED = "FAST_VALIDATION_STARTED"
    FAST_VALIDATION_PASSED = "FAST_VALIDATION_PASSED"
    FAST_VALIDATION_FAILED = "FAST_VALIDATION_FAILED"
    STAGE_PROMOTED = "STAGE_PROMOTED"
    STAGE_REJECTED = "STAGE_REJECTED"
    STRATEGY_KILLED = "STRATEGY_KILLED"
    STRATEGY_DEMOTED = "STRATEGY_DEMOTED"
    STRATEGY_RETIRED = "STRATEGY_RETIRED"
    OVERRIDE_ATTEMPTED = "OVERRIDE_ATTEMPTED"
    OVERRIDE_APPROVED = "OVERRIDE_APPROVED"
    OVERRIDE_REJECTED = "OVERRIDE_REJECTED"
    TRADE_APPROVED = "TRADE_APPROVED"
    TRADE_REJECTED = "TRADE_REJECTED"
    RISK_LIMIT_HIT = "RISK_LIMIT_HIT"
    PAPER_STARTED = "PAPER_STARTED"
    MICRO_LIVE_STARTED = "MICRO_LIVE_STARTED"
    FULL_LIVE_STARTED = "FULL_LIVE_STARTED"


class OverrideResult(str, Enum):
    """Outcome of an override request."""
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PENDING = "PENDING"


class TradeResult(str, Enum):
    """Outcome of a trade."""
    WIN = "WIN"
    LOSS = "LOSS"
    BREAKEVEN = "BREAKEVEN"


class SystemMode(str, Enum):
    """Global system operating mode."""
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    HALTED = "HALTED"
