"""
Base Strategy Executor — shared framework all 6 agents inherit from.

Takes a validated StrategyDNA + MarketContext → generates TradeSignals.
Implements multi-timeframe logic: 4h bias → 1h confirmation → 15m setup → 5m entry.
"""
from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── Data Models ──────────────────────────────────────────────────────────────

class Bias(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class Confirmation(str, Enum):
    CONFIRMED = "confirmed"
    NOT_CONFIRMED = "not_confirmed"


class SetupStatus(str, Enum):
    SETUP_FOUND = "setup_found"
    NO_SETUP = "no_setup"


class SignalDirection(str, Enum):
    LONG = "long"
    SHORT = "short"


class TradeStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class TradeOutcome(str, Enum):
    WIN = "win"
    LOSS = "loss"
    BREAKEVEN = "breakeven"
    OPEN = "open"


@dataclass
class BiasResult:
    bias: Bias
    confidence: float  # 0.0 - 1.0
    rationale: str
    indicators: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConfirmationResult:
    status: Confirmation
    confidence: float
    rationale: str
    indicators: dict[str, Any] = field(default_factory=dict)


@dataclass
class SetupResult:
    status: SetupStatus
    pattern: str = ""
    rationale: str = ""
    key_level: float = 0.0
    indicators: dict[str, Any] = field(default_factory=dict)


@dataclass
class EntrySignal:
    direction: SignalDirection
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: Optional[float] = None
    rationale: str = ""
    confidence: float = 0.0
    indicators: dict[str, Any] = field(default_factory=dict)


@dataclass
class TradeSignal:
    """Complete trade signal ready for Overseer approval."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str = ""
    strategy_code: str = ""
    instrument: str = ""
    direction: SignalDirection = SignalDirection.LONG
    entry_price: float = 0.0
    stop_loss: float = 0.0
    target_1: float = 0.0
    target_2: Optional[float] = None
    position_size: float = 0.0
    risk_amount: float = 0.0
    reward_risk_ratio: float = 0.0
    bias: BiasResult = field(default_factory=lambda: BiasResult(Bias.NEUTRAL, 0.0, ""))
    confirmation: ConfirmationResult = field(
        default_factory=lambda: ConfirmationResult(Confirmation.NOT_CONFIRMED, 0.0, "")
    )
    setup: SetupResult = field(default_factory=lambda: SetupResult(SetupStatus.NO_SETUP))
    entry: Optional[EntrySignal] = None
    composite_confidence: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: TradeStatus = TradeStatus.PENDING_APPROVAL
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "strategy_code": self.strategy_code,
            "instrument": self.instrument,
            "direction": self.direction.value,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "target_1": self.target_1,
            "target_2": self.target_2,
            "position_size": self.position_size,
            "risk_amount": self.risk_amount,
            "reward_risk_ratio": self.reward_risk_ratio,
            "composite_confidence": self.composite_confidence,
            "timestamp": self.timestamp,
            "status": self.status.value,
            "rationale": self.rationale,
            "bias": {
                "direction": self.bias.bias.value,
                "confidence": self.bias.confidence,
                "rationale": self.bias.rationale,
            },
            "confirmation": {
                "status": self.confirmation.status.value,
                "confidence": self.confirmation.confidence,
                "rationale": self.confirmation.rationale,
            },
            "setup": {
                "status": self.setup.status.value,
                "pattern": self.setup.pattern,
                "rationale": self.setup.rationale,
            },
        }


@dataclass
class TradeRecord:
    """Completed trade with outcome."""
    signal: TradeSignal
    outcome: TradeOutcome = TradeOutcome.OPEN
    exit_price: float = 0.0
    pnl: float = 0.0
    r_multiple: float = 0.0
    exit_reason: str = ""
    exit_time: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.signal.to_dict(),
            "outcome": self.outcome.value,
            "exit_price": self.exit_price,
            "pnl": self.pnl,
            "r_multiple": self.r_multiple,
            "exit_reason": self.exit_reason,
            "exit_time": self.exit_time,
        }


# ── Market Context Type ──────────────────────────────────────────────────────

@dataclass
class TimeframeData:
    """Parsed market data for one timeframe."""
    ohlc: dict[str, float] = field(default_factory=lambda: {"open": 0, "high": 0, "low": 0, "close": 0})
    volume: int = 0
    vwap: float = 0.0
    rsi: float = 50.0
    atr: float = 0.0
    ema_20: float = 0.0
    ema_50: float = 0.0
    trend: str = "neutral"
    support: float = 0.0
    resistance: float = 0.0
    timestamp: str = ""
    # Extended fields agents can populate
    adx: float = 0.0
    macd: float = 0.0
    macd_signal: float = 0.0
    macd_histogram: float = 0.0
    bb_upper: float = 0.0
    bb_lower: float = 0.0
    bb_middle: float = 0.0
    bb_width: float = 0.0
    stochastic_k: float = 50.0
    stochastic_d: float = 50.0
    cvd: float = 0.0
    delta: float = 0.0
    poc: float = 0.0
    vah: float = 0.0
    val: float = 0.0
    avg_volume: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TimeframeData":
        if "error" in data:
            return cls()
        ohlc = data.get("ohlc", {"open": 0, "high": 0, "low": 0, "close": 0})
        return cls(
            ohlc=ohlc,
            volume=data.get("volume", 0),
            vwap=data.get("vwap", ohlc.get("close", 0)),
            rsi=data.get("rsi", 50.0),
            atr=data.get("atr", 0.0),
            ema_20=data.get("ema_20", ohlc.get("close", 0)),
            ema_50=data.get("ema_50", ohlc.get("close", 0)),
            trend=data.get("trend", "neutral"),
            support=data.get("support", ohlc.get("low", 0)),
            resistance=data.get("resistance", ohlc.get("high", 0)),
            timestamp=data.get("timestamp", ""),
            adx=data.get("adx", 0.0),
            macd=data.get("macd", 0.0),
            macd_signal=data.get("macd_signal", 0.0),
            macd_histogram=data.get("macd_histogram", 0.0),
            bb_upper=data.get("bb_upper", 0.0),
            bb_lower=data.get("bb_lower", 0.0),
            bb_middle=data.get("bb_middle", 0.0),
            bb_width=data.get("bb_width", 0.0),
            stochastic_k=data.get("stochastic_k", 50.0),
            stochastic_d=data.get("stochastic_d", 50.0),
            cvd=data.get("cvd", 0.0),
            delta=data.get("delta", 0.0),
            poc=data.get("poc", 0.0),
            vah=data.get("vah", 0.0),
            val=data.get("val", 0.0),
            avg_volume=data.get("avg_volume", 0),
        )


@dataclass
class MarketContext:
    """Complete market state across all timeframes for one instrument."""
    instrument: str = ""
    timestamp: str = ""
    tf_4h: TimeframeData = field(default_factory=TimeframeData)
    tf_1h: TimeframeData = field(default_factory=TimeframeData)
    tf_15m: TimeframeData = field(default_factory=TimeframeData)
    tf_5m: TimeframeData = field(default_factory=TimeframeData)
    # Additional context
    news_events: list[dict[str, Any]] = field(default_factory=list)
    session_info: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MarketContext":
        return cls(
            instrument=data.get("instrument", ""),
            timestamp=data.get("timestamp", ""),
            tf_4h=TimeframeData.from_dict(data.get("4h", {})),
            tf_1h=TimeframeData.from_dict(data.get("1h", {})),
            tf_15m=TimeframeData.from_dict(data.get("15m", {})),
            tf_5m=TimeframeData.from_dict(data.get("5m", {})),
            news_events=data.get("news_events", []),
            session_info=data.get("session_info", {}),
        )


# ── Strategy DNA Type ────────────────────────────────────────────────────────

@dataclass
class StrategyDNA:
    """Parsed strategy configuration from strategy_dnas.json."""
    strategy_code: str = ""
    style: str = ""
    template: str = ""
    timeframe_logic: dict[str, str] = field(default_factory=dict)
    hypothesis: str = ""
    entry_rules: str = ""
    exit_rules: str = ""
    stop_loss: str = ""
    filters: list[str] = field(default_factory=list)
    parameter_ranges: dict[str, Any] = field(default_factory=dict)
    expected_behavior: dict[str, str] = field(default_factory=dict)
    invalidation: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StrategyDNA":
        return cls(
            strategy_code=data.get("strategy_code", ""),
            style=data.get("style", ""),
            template=data.get("template", ""),
            timeframe_logic=data.get("timeframe_logic", {}),
            hypothesis=data.get("hypothesis", ""),
            entry_rules=data.get("entry_rules", ""),
            exit_rules=data.get("exit_rules", ""),
            stop_loss=data.get("stop_loss", ""),
            filters=data.get("filters", []),
            parameter_ranges=data.get("parameter_ranges", {}),
            expected_behavior=data.get("expected_behavior", {}),
            invalidation=data.get("invalidation", ""),
        )


# ── Base Executor ─────────────────────────────────────────────────────────────

class BaseExecutor(ABC):
    """
    Base class for all 6 strategy executor agents.

    Multi-timeframe cascade:
        4h bias → 1h confirmation → 15m setup → 5m entry

    Each subclass implements the 4 abstract check methods with
    strategy-specific logic derived from its StrategyDNA.
    """

    # Subclasses set these
    AGENT_ID: str = "base"
    AGENT_NAME: str = "Base Executor"
    STYLE: str = "unknown"

    # Risk defaults
    DEFAULT_RISK_PER_TRADE: float = 0.01  # 1% of account
    DEFAULT_ACCOUNT_SIZE: float = 100_000.0
    MAX_CONCURRENT_TRADES: int = 3
    MIN_COMPOSITE_CONFIDENCE: float = 0.5

    def __init__(self, dna: StrategyDNA, account_size: float = 100_000.0):
        self.dna = dna
        self.account_size = account_size
        self.trade_history: list[TradeRecord] = []
        self.open_trades: list[TradeSignal] = []
        self.signals_generated: int = 0
        self.signals_approved: int = 0
        self.signals_rejected: int = 0
        self.active: bool = True
        self._logger = logging.getLogger(f"executor.{self.AGENT_ID}")

    # ── Abstract methods — each agent implements these ────────────────────

    @abstractmethod
    def check_bias(self, context_4h: TimeframeData) -> BiasResult:
        """Analyze 4h timeframe for macro directional bias."""
        ...

    @abstractmethod
    def check_confirmation(self, context_1h: TimeframeData, bias: BiasResult) -> ConfirmationResult:
        """Confirm 1h aligns with 4h bias."""
        ...

    @abstractmethod
    def check_setup(self, context_15m: TimeframeData, bias: BiasResult, confirmation: ConfirmationResult) -> SetupResult:
        """Look for trade setup pattern on 15m."""
        ...

    @abstractmethod
    def check_entry(self, context_5m: TimeframeData, bias: BiasResult, setup: SetupResult) -> Optional[EntrySignal]:
        """Determine precise entry on 5m."""
        ...

    # ── Core execution pipeline ──────────────────────────────────────────

    def generate_signal(self, market_context: MarketContext) -> Optional[TradeSignal]:
        """
        Run the full multi-timeframe cascade.
        Returns a TradeSignal if all checks pass, None otherwise.
        """
        if not self.active:
            self._logger.info(f"[{self.AGENT_ID}] Agent inactive, skipping")
            return None

        if len(self.open_trades) >= self.MAX_CONCURRENT_TRADES:
            self._logger.info(f"[{self.AGENT_ID}] Max concurrent trades reached ({self.MAX_CONCURRENT_TRADES})")
            return None

        instrument = market_context.instrument
        self._logger.info(f"[{self.AGENT_ID}] Analyzing {instrument} with DNA {self.dna.strategy_code}")

        # Step 1: 4h Bias
        bias = self.check_bias(market_context.tf_4h)
        self._logger.info(f"[{self.AGENT_ID}] 4h Bias: {bias.bias.value} (conf: {bias.confidence:.2f}) — {bias.rationale}")

        if bias.bias == Bias.NEUTRAL and bias.confidence < 0.3:
            self._logger.info(f"[{self.AGENT_ID}] No clear bias, skipping")
            return None

        # Step 2: 1h Confirmation
        confirmation = self.check_confirmation(market_context.tf_1h, bias)
        self._logger.info(
            f"[{self.AGENT_ID}] 1h Confirmation: {confirmation.status.value} "
            f"(conf: {confirmation.confidence:.2f}) — {confirmation.rationale}"
        )

        if confirmation.status == Confirmation.NOT_CONFIRMED:
            self._logger.info(f"[{self.AGENT_ID}] 1h does not confirm 4h bias, skipping")
            return None

        # Step 3: 15m Setup
        setup = self.check_setup(market_context.tf_15m, bias, confirmation)
        self._logger.info(
            f"[{self.AGENT_ID}] 15m Setup: {setup.status.value} — {setup.pattern} — {setup.rationale}"
        )

        if setup.status == SetupStatus.NO_SETUP:
            self._logger.info(f"[{self.AGENT_ID}] No setup found on 15m, skipping")
            return None

        # Step 4: 5m Entry
        entry = self.check_entry(market_context.tf_5m, bias, setup)

        if entry is None:
            self._logger.info(f"[{self.AGENT_ID}] No entry trigger on 5m, skipping")
            return None

        self._logger.info(
            f"[{self.AGENT_ID}] 5m Entry: {entry.direction.value} @ {entry.entry_price:.2f} "
            f"SL={entry.stop_loss:.2f} TP={entry.target_1:.2f}"
        )

        # Build signal
        signal = self._build_signal(market_context, bias, confirmation, setup, entry)

        # Check composite confidence threshold
        if signal.composite_confidence < self.MIN_COMPOSITE_CONFIDENCE:
            self._logger.info(
                f"[{self.AGENT_ID}] Composite confidence {signal.composite_confidence:.2f} "
                f"below threshold {self.MIN_COMPOSITE_CONFIDENCE}, skipping"
            )
            return None

        self.signals_generated += 1
        self._logger.info(
            f"[{self.AGENT_ID}] ✅ SIGNAL GENERATED: {signal.direction.value} {instrument} "
            f"@ {signal.entry_price:.2f} | RR={signal.reward_risk_ratio:.2f} | "
            f"Conf={signal.composite_confidence:.2f}"
        )

        return signal

    def _build_signal(
        self,
        ctx: MarketContext,
        bias: BiasResult,
        confirmation: ConfirmationResult,
        setup: SetupResult,
        entry: EntrySignal,
    ) -> TradeSignal:
        """Assemble all check results into a complete TradeSignal."""
        risk_per_point = abs(entry.entry_price - entry.stop_loss)
        if risk_per_point == 0:
            risk_per_point = ctx.tf_5m.atr or 1.0

        reward_1 = abs(entry.target_1 - entry.entry_price)
        rr_ratio = reward_1 / risk_per_point if risk_per_point > 0 else 0.0

        # Position sizing: risk 1% of account
        risk_amount = self.account_size * self.DEFAULT_RISK_PER_TRADE
        position_size = risk_amount / risk_per_point if risk_per_point > 0 else 0.0

        # Composite confidence: weighted average of all stages
        composite = (
            bias.confidence * 0.25
            + confirmation.confidence * 0.25
            + (0.8 if setup.status == SetupStatus.SETUP_FOUND else 0.0) * 0.25
            + entry.confidence * 0.25
        )

        rationale = (
            f"4h: {bias.rationale} | "
            f"1h: {confirmation.rationale} | "
            f"15m: {setup.rationale} | "
            f"5m: {entry.rationale}"
        )

        return TradeSignal(
            agent_id=self.AGENT_ID,
            strategy_code=self.dna.strategy_code,
            instrument=ctx.instrument,
            direction=entry.direction,
            entry_price=entry.entry_price,
            stop_loss=entry.stop_loss,
            target_1=entry.target_1,
            target_2=entry.target_2,
            position_size=round(position_size, 2),
            risk_amount=round(risk_amount, 2),
            reward_risk_ratio=round(rr_ratio, 2),
            bias=bias,
            confirmation=confirmation,
            setup=setup,
            entry=entry,
            composite_confidence=round(composite, 3),
            rationale=rationale,
        )

    # ── Trade lifecycle ──────────────────────────────────────────────────

    def on_approved(self, signal: TradeSignal) -> None:
        """Called when Overseer approves a signal."""
        signal.status = TradeStatus.APPROVED
        self.open_trades.append(signal)
        self.signals_approved += 1
        self._logger.info(f"[{self.AGENT_ID}] Trade APPROVED: {signal.id}")

    def on_rejected(self, signal: TradeSignal, reason: str = "") -> None:
        """Called when Overseer rejects a signal."""
        signal.status = TradeStatus.REJECTED
        self.signals_rejected += 1
        record = TradeRecord(signal=signal, outcome=TradeOutcome.LOSS, exit_reason=f"rejected: {reason}")
        self.trade_history.append(record)
        self._logger.info(f"[{self.AGENT_ID}] Trade REJECTED: {signal.id} — {reason}")

    def close_trade(
        self,
        signal: TradeSignal,
        exit_price: float,
        exit_reason: str = "target_hit",
    ) -> TradeRecord:
        """Close an open trade and record the outcome."""
        risk_per_point = abs(signal.entry_price - signal.stop_loss) or 1.0

        if signal.direction == SignalDirection.LONG:
            pnl = exit_price - signal.entry_price
        else:
            pnl = signal.entry_price - exit_price

        r_multiple = pnl / risk_per_point

        if r_multiple > 0.1:
            outcome = TradeOutcome.WIN
        elif r_multiple < -0.1:
            outcome = TradeOutcome.LOSS
        else:
            outcome = TradeOutcome.BREAKEVEN

        signal.status = TradeStatus.CLOSED
        record = TradeRecord(
            signal=signal,
            outcome=outcome,
            exit_price=exit_price,
            pnl=round(pnl * signal.position_size, 2),
            r_multiple=round(r_multiple, 2),
            exit_reason=exit_reason,
            exit_time=datetime.now(timezone.utc).isoformat(),
        )

        if signal in self.open_trades:
            self.open_trades.remove(signal)
        self.trade_history.append(record)

        self._logger.info(
            f"[{self.AGENT_ID}] Trade CLOSED: {signal.id} | "
            f"{outcome.value} | R={r_multiple:.2f} | PnL={record.pnl:.2f} | {exit_reason}"
        )

        return record

    # ── Stats / Status ───────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Return agent status summary."""
        wins = sum(1 for t in self.trade_history if t.outcome == TradeOutcome.WIN)
        losses = sum(1 for t in self.trade_history if t.outcome == TradeOutcome.LOSS)
        total = wins + losses

        return {
            "agent_id": self.AGENT_ID,
            "agent_name": self.AGENT_NAME,
            "style": self.STYLE,
            "strategy_code": self.dna.strategy_code,
            "active": self.active,
            "signals_generated": self.signals_generated,
            "signals_approved": self.signals_approved,
            "signals_rejected": self.signals_rejected,
            "open_trades": len(self.open_trades),
            "total_closed": len(self.trade_history),
            "win_rate": round(wins / total, 3) if total > 0 else 0.0,
            "total_pnl": round(sum(t.pnl for t in self.trade_history), 2),
            "avg_r": round(
                sum(t.r_multiple for t in self.trade_history) / len(self.trade_history), 2
            ) if self.trade_history else 0.0,
        }

    def get_trades(self) -> list[dict[str, Any]]:
        """Return trade history as dicts."""
        return [t.to_dict() for t in self.trade_history]
