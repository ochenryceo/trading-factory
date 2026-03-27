"""
Overseer Approval Pipeline — every trade passes through here before execution.

Checks global risk limits, logs approvals/rejections to audit trail,
and computes capital allocation based on alignment score.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from services.overseer.decision_engine import (
    Decision,
    RiskLevel,
    TradeDecision,
    TradeSignal,
)

logger = logging.getLogger("overseer.approvals")


# --------------------------------------------------------------------------- #
# Risk Limits (Global)                                                        #
# --------------------------------------------------------------------------- #

@dataclass
class GlobalRiskLimits:
    """System-wide risk constraints checked before every approval."""
    max_daily_loss: float = 5000.0          # USD
    max_open_positions: int = 6
    max_exposure_pct: float = 0.20          # 20% of capital
    max_correlated_positions: int = 3       # same-asset or highly correlated
    max_single_position_pct: float = 0.05   # 5% of capital per position
    min_capital_reserve_pct: float = 0.30   # always keep 30% in reserve
    trading_halted: bool = False


@dataclass
class RiskState:
    """Current risk state tracked in-memory (persisted externally)."""
    daily_pnl: float = 0.0
    open_positions: int = 0
    total_exposure: float = 0.0
    capital: float = 100_000.0
    positions_by_asset: dict[str, int] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Audit Trail                                                                 #
# --------------------------------------------------------------------------- #

@dataclass
class AuditEntry:
    """Immutable record of every approval decision."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    signal_strategy: str = ""
    signal_asset: str = ""
    signal_direction: str = ""
    decision: str = ""
    reason: str = ""
    score: float = 0.0
    capital_allocated: float = 0.0
    risk_checks_passed: bool = True
    risk_check_details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "signal_strategy": self.signal_strategy,
            "signal_asset": self.signal_asset,
            "signal_direction": self.signal_direction,
            "decision": self.decision,
            "reason": self.reason,
            "score": round(self.score, 4),
            "capital_allocated": round(self.capital_allocated, 2),
            "risk_checks_passed": self.risk_checks_passed,
            "risk_check_details": self.risk_check_details,
        }


# --------------------------------------------------------------------------- #
# Capital Allocation                                                          #
# --------------------------------------------------------------------------- #

def compute_capital_allocation(
    alignment_score: float,
    final_score: float,
    capital: float,
    max_single_pct: float,
) -> float:
    """
    Allocate capital based on alignment + decision score.

    Strong alignment (≥0.7) → up to max_single_pct of capital
    Moderate alignment (0.4-0.7) → half allocation
    Weak/conflict (≤0.3) → zero
    """
    max_alloc = capital * max_single_pct

    if alignment_score >= 1.0:
        base = max_alloc
    elif alignment_score >= 0.7:
        base = max_alloc * 0.75
    elif alignment_score > 0.3:
        base = max_alloc * 0.40
    else:
        return 0.0  # conflict → zero allocation

    # Scale by final score
    return base * min(final_score / 0.7, 1.0)


# --------------------------------------------------------------------------- #
# Approval Pipeline                                                           #
# --------------------------------------------------------------------------- #

class ApprovalPipeline:
    """
    Every trade flows through this pipeline before execution.

    1. Check if trading is halted
    2. Check global risk limits
    3. Compute capital allocation
    4. Log to audit trail
    5. Return final approval with execution parameters
    """

    def __init__(
        self,
        risk_limits: GlobalRiskLimits | None = None,
        risk_state: RiskState | None = None,
    ) -> None:
        self.limits = risk_limits or GlobalRiskLimits()
        self.state = risk_state or RiskState()
        self.audit_trail: list[AuditEntry] = []

    # ------------------------------------------------------------------ #
    # Risk Checks                                                        #
    # ------------------------------------------------------------------ #

    def check_risk_limits(self, signal: TradeSignal, trade_decision: TradeDecision) -> tuple[bool, dict[str, Any]]:
        """
        Run all global risk checks. Returns (passed, details).
        """
        checks: dict[str, Any] = {}

        # 1. Trading halted?
        if self.limits.trading_halted:
            checks["trading_halted"] = "FAIL: Trading is globally halted"
            return False, checks
        checks["trading_halted"] = "PASS"

        # 2. Daily loss limit
        if self.state.daily_pnl <= -self.limits.max_daily_loss:
            checks["daily_loss"] = f"FAIL: Daily loss ${abs(self.state.daily_pnl):.2f} >= limit ${self.limits.max_daily_loss:.2f}"
            return False, checks
        checks["daily_loss"] = f"PASS: ${abs(self.state.daily_pnl):.2f} < ${self.limits.max_daily_loss:.2f}"

        # 3. Max open positions
        if self.state.open_positions >= self.limits.max_open_positions:
            checks["max_positions"] = f"FAIL: {self.state.open_positions} >= {self.limits.max_open_positions}"
            return False, checks
        checks["max_positions"] = f"PASS: {self.state.open_positions} < {self.limits.max_open_positions}"

        # 4. Max exposure
        exposure_pct = self.state.total_exposure / max(self.state.capital, 1)
        if exposure_pct >= self.limits.max_exposure_pct:
            checks["max_exposure"] = f"FAIL: {exposure_pct:.1%} >= {self.limits.max_exposure_pct:.1%}"
            return False, checks
        checks["max_exposure"] = f"PASS: {exposure_pct:.1%} < {self.limits.max_exposure_pct:.1%}"

        # 5. Correlated positions
        asset_count = self.state.positions_by_asset.get(signal.asset, 0)
        if asset_count >= self.limits.max_correlated_positions:
            checks["correlated"] = f"FAIL: {asset_count} {signal.asset} positions >= {self.limits.max_correlated_positions}"
            return False, checks
        checks["correlated"] = f"PASS: {asset_count} < {self.limits.max_correlated_positions}"

        # 6. Capital reserve
        available = self.state.capital - self.state.total_exposure
        reserve_needed = self.state.capital * self.limits.min_capital_reserve_pct
        if available < reserve_needed:
            checks["reserve"] = f"FAIL: Available ${available:.2f} < reserve ${reserve_needed:.2f}"
            return False, checks
        checks["reserve"] = f"PASS: Available ${available:.2f} >= reserve ${reserve_needed:.2f}"

        return True, checks

    # ------------------------------------------------------------------ #
    # Core Approve Method                                                #
    # ------------------------------------------------------------------ #

    def process(self, trade_decision: TradeDecision) -> dict[str, Any]:
        """
        Process a TradeDecision through the approval pipeline.

        Returns execution parameters if approved, rejection details otherwise.
        """
        signal = trade_decision.signal

        # Already rejected by decision engine?
        if trade_decision.decision == Decision.REJECT:
            entry = self._log_audit(signal, trade_decision, passed=False, capital=0.0, checks={})
            return {
                "approved": False,
                "decision": "REJECT",
                "reason": trade_decision.reason,
                "audit_id": entry.id,
            }

        # Run risk checks
        passed, checks = self.check_risk_limits(signal, trade_decision)

        if not passed:
            entry = self._log_audit(signal, trade_decision, passed=False, capital=0.0, checks=checks)
            failed = [k for k, v in checks.items() if "FAIL" in str(v)]
            return {
                "approved": False,
                "decision": "REJECT_RISK",
                "reason": f"Risk check failed: {', '.join(failed)}",
                "risk_checks": checks,
                "audit_id": entry.id,
            }

        # Compute capital allocation
        capital_alloc = compute_capital_allocation(
            alignment_score=trade_decision.alignment_score,
            final_score=trade_decision.score,
            capital=self.state.capital,
            max_single_pct=self.limits.max_single_position_pct,
        )

        if capital_alloc <= 0:
            entry = self._log_audit(signal, trade_decision, passed=True, capital=0.0, checks=checks)
            return {
                "approved": False,
                "decision": "REJECT_ALLOCATION",
                "reason": "Zero capital allocation — alignment too weak",
                "audit_id": entry.id,
            }

        # Approved!
        entry = self._log_audit(signal, trade_decision, passed=True, capital=capital_alloc, checks=checks)

        result: dict[str, Any] = {
            "approved": True,
            "decision": trade_decision.decision.value,
            "capital_allocated": round(capital_alloc, 2),
            "score": round(trade_decision.score, 4),
            "risk_checks": checks,
            "audit_id": entry.id,
        }

        if trade_decision.decision == Decision.MODIFY:
            result["modifications"] = trade_decision.modifications

        return result

    # ------------------------------------------------------------------ #
    # Audit Logging                                                      #
    # ------------------------------------------------------------------ #

    def _log_audit(
        self,
        signal: TradeSignal,
        decision: TradeDecision,
        passed: bool,
        capital: float,
        checks: dict[str, Any],
    ) -> AuditEntry:
        entry = AuditEntry(
            signal_strategy=signal.strategy_name,
            signal_asset=signal.asset,
            signal_direction=signal.direction.value,
            decision=decision.decision.value,
            reason=decision.reason,
            score=decision.score,
            capital_allocated=capital,
            risk_checks_passed=passed,
            risk_check_details=checks,
        )
        self.audit_trail.append(entry)
        logger.info(
            "AUDIT [%s] %s/%s → %s (capital=$%.2f)",
            entry.id[:8],
            signal.strategy_name,
            signal.asset,
            decision.decision.value,
            capital,
        )
        return entry

    def get_audit_trail(self, limit: int = 50) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.audit_trail[-limit:]]
