"""
Signal Router — runs all 6 executor agents against current MarketContext,
collects signals, sends to Overseer for approval, executes approved trades.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .base_executor import (
    BaseExecutor,
    MarketContext,
    StrategyDNA,
    TradeSignal,
    TradeStatus,
)
from .alpha.strategy import AlphaExecutor
from .bravo.strategy import BravoExecutor
from .charlie.strategy import CharlieExecutor
from .delta.strategy import DeltaExecutor
from .echo.strategy import EchoExecutor
from .foxtrot.strategy import FoxtrotExecutor

logger = logging.getLogger(__name__)

# Style → Executor class mapping
EXECUTOR_REGISTRY: dict[str, type[BaseExecutor]] = {
    "momentum_breakout": AlphaExecutor,
    "mean_reversion": BravoExecutor,
    "scalping": CharlieExecutor,
    "trend_following": DeltaExecutor,
    "news_reaction": EchoExecutor,
    "volume_orderflow": FoxtrotExecutor,
}


@dataclass
class OverseerDecision:
    """Result of Overseer review."""
    signal_id: str
    approved: bool
    reason: str = ""
    risk_adjustment: Optional[float] = None  # position size multiplier


@dataclass
class RunResult:
    """Result of running all agents against market state."""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    instrument: str = ""
    signals_generated: list[dict[str, Any]] = field(default_factory=list)
    signals_approved: list[dict[str, Any]] = field(default_factory=list)
    signals_rejected: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)


class SignalRouter:
    """
    Orchestrates all 6 executor agents.

    Workflow:
    1. Load StrategyDNA for each agent
    2. Run each agent against current MarketContext
    3. Collect signals
    4. Send to Overseer for approval
    5. Execute approved trades, log rejected ones
    """

    def __init__(self, dna_configs: list[dict[str, Any]], account_size: float = 100_000.0):
        self.agents: dict[str, BaseExecutor] = {}
        self.account_size = account_size
        self.run_history: list[RunResult] = []

        self._initialize_agents(dna_configs)

    def _initialize_agents(self, dna_configs: list[dict[str, Any]]) -> None:
        """Create one agent per style, using the first DNA found for each style."""
        style_to_dna: dict[str, StrategyDNA] = {}

        for config in dna_configs:
            style = config.get("style", "")
            if style not in style_to_dna:
                style_to_dna[style] = StrategyDNA.from_dict(config)

        for style, dna in style_to_dna.items():
            executor_cls = EXECUTOR_REGISTRY.get(style)
            if executor_cls:
                agent = executor_cls(dna, self.account_size)
                self.agents[agent.AGENT_ID] = agent
                logger.info(f"Initialized {agent.AGENT_NAME} with DNA {dna.strategy_code}")
            else:
                logger.warning(f"No executor registered for style: {style}")

    def run_all(self, market_context: MarketContext, auto_approve: bool = False) -> RunResult:
        """
        Run all agents against the current market state.

        Args:
            market_context: Current market state across all timeframes.
            auto_approve: If True, skip Overseer and auto-approve all signals.
                          Use for backtesting/paper trading only.
        """
        result = RunResult(instrument=market_context.instrument)

        for agent_id, agent in self.agents.items():
            try:
                signal = agent.generate_signal(market_context)
                if signal:
                    result.signals_generated.append(signal.to_dict())

                    if auto_approve:
                        decision = OverseerDecision(
                            signal_id=signal.id,
                            approved=True,
                            reason="auto_approved",
                        )
                    else:
                        decision = self._submit_to_overseer(signal)

                    if decision.approved:
                        if decision.risk_adjustment:
                            signal.position_size *= decision.risk_adjustment
                        agent.on_approved(signal)
                        result.signals_approved.append(signal.to_dict())
                        logger.info(f"✅ APPROVED: {agent_id} — {signal.direction.value} {signal.instrument}")
                    else:
                        agent.on_rejected(signal, decision.reason)
                        result.signals_rejected.append({
                            **signal.to_dict(),
                            "rejection_reason": decision.reason,
                        })
                        logger.info(f"❌ REJECTED: {agent_id} — {decision.reason}")

            except Exception as e:
                error_msg = f"Agent {agent_id} error: {str(e)}"
                logger.error(error_msg, exc_info=True)
                result.errors.append({"agent_id": agent_id, "error": error_msg})

        self.run_history.append(result)
        return result

    def _submit_to_overseer(self, signal: TradeSignal) -> OverseerDecision:
        """
        Submit signal to Overseer for approval.

        In production, this calls the Overseer service via HTTP.
        For now, applies basic risk checks locally.
        """
        # Basic risk checks (placeholder — Overseer service will do this properly)
        reasons = []

        # Check R:R minimum
        if signal.reward_risk_ratio < 1.0:
            reasons.append(f"R:R too low ({signal.reward_risk_ratio:.2f})")

        # Check confidence minimum
        if signal.composite_confidence < 0.4:
            reasons.append(f"Confidence too low ({signal.composite_confidence:.2f})")

        # Check position size sanity
        if signal.position_size <= 0:
            reasons.append("Invalid position size")

        if reasons:
            return OverseerDecision(
                signal_id=signal.id,
                approved=False,
                reason="; ".join(reasons),
            )

        return OverseerDecision(
            signal_id=signal.id,
            approved=True,
            reason="passed_risk_checks",
        )

    def get_all_agents_status(self) -> list[dict[str, Any]]:
        """Get status for all agents."""
        return [agent.get_status() for agent in self.agents.values()]

    def get_agent(self, agent_id: str) -> Optional[BaseExecutor]:
        """Get a specific agent by ID."""
        return self.agents.get(agent_id)

    def get_agent_trades(self, agent_id: str) -> list[dict[str, Any]]:
        """Get trade history for a specific agent."""
        agent = self.agents.get(agent_id)
        if agent:
            return agent.get_trades()
        return []
