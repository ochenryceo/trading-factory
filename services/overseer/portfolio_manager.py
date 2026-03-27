"""
Overseer Portfolio Manager — exposure tracking, position sizing, and daily loss management.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from services.overseer.decision_engine import Direction, RiskLevel

logger = logging.getLogger("overseer.portfolio")


# --------------------------------------------------------------------------- #
# Position & Portfolio Models                                                 #
# --------------------------------------------------------------------------- #

@dataclass
class Position:
    """A single open position."""
    position_id: str
    strategy_id: str
    asset: str
    direction: Direction
    size: float              # notional USD
    entry_price: float
    stop_loss: float | None = None
    take_profit: float | None = None
    unrealized_pnl: float = 0.0
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def risk_amount(self) -> float:
        """Max loss if stop is hit."""
        if self.stop_loss is None or self.entry_price == 0:
            return self.size * 0.02  # default 2% risk estimate
        pct = abs(self.entry_price - self.stop_loss) / self.entry_price
        return self.size * pct


# Asset correlation groups — assets in the same group count as correlated
CORRELATION_GROUPS: dict[str, str] = {
    "NQ": "equity_index",
    "ES": "equity_index",
    "YM": "equity_index",
    "RTY": "equity_index",
    "GC": "precious_metals",
    "SI": "precious_metals",
    "CL": "energy",
    "NG": "energy",
}


class PortfolioManager:
    """
    Tracks total portfolio exposure, enforces position limits,
    manages daily loss tracking, and computes position sizing.
    """

    # Limits
    MAX_TOTAL_EXPOSURE_PCT = 0.60       # 60% of capital
    MAX_CORRELATED_POSITIONS = 3
    MAX_SINGLE_ASSET_POSITIONS = 2
    DAILY_LOSS_LIMIT = 5000.0           # USD
    MAX_PORTFOLIO_RISK_PCT = 0.02       # 2% of capital at risk at any time

    def __init__(self, capital: float = 100_000.0) -> None:
        self.capital = capital
        self.positions: dict[str, Position] = {}  # position_id → Position
        self.daily_realized_pnl: float = 0.0
        self.daily_trades: int = 0
        self._closed_today: list[dict[str, Any]] = []
        self._last_reset: datetime = datetime.now(timezone.utc)

    # ------------------------------------------------------------------ #
    # Exposure Calculations                                              #
    # ------------------------------------------------------------------ #

    @property
    def total_exposure(self) -> float:
        return sum(p.size for p in self.positions.values())

    @property
    def exposure_pct(self) -> float:
        return self.total_exposure / max(self.capital, 1)

    @property
    def total_risk(self) -> float:
        return sum(p.risk_amount for p in self.positions.values())

    @property
    def open_position_count(self) -> int:
        return len(self.positions)

    def positions_by_asset(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for p in self.positions.values():
            counts[p.asset] = counts.get(p.asset, 0) + 1
        return counts

    def positions_by_correlation_group(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for p in self.positions.values():
            group = CORRELATION_GROUPS.get(p.asset, p.asset)
            counts[group] = counts.get(group, 0) + 1
        return counts

    @property
    def net_daily_pnl(self) -> float:
        unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        return self.daily_realized_pnl + unrealized

    # ------------------------------------------------------------------ #
    # Position Sizing                                                    #
    # ------------------------------------------------------------------ #

    def compute_position_size(
        self,
        alignment_score: float,
        risk_budget_pct: float = 0.01,  # 1% of capital per trade default
        risk_level: RiskLevel = RiskLevel.MEDIUM,
    ) -> float:
        """
        Compute position size in USD based on alignment score + risk budget.

        alignment ≥ 1.0 → full risk budget
        alignment ≥ 0.7 → 75% of budget
        alignment < 0.7 → 50% of budget
        """
        base_risk = self.capital * risk_budget_pct

        # Scale by alignment
        if alignment_score >= 1.0:
            scale = 1.0
        elif alignment_score >= 0.7:
            scale = 0.75
        else:
            scale = 0.50

        # Reduce for higher risk levels
        risk_multiplier = {
            RiskLevel.LOW: 1.2,
            RiskLevel.MEDIUM: 1.0,
            RiskLevel.HIGH: 0.6,
            RiskLevel.EXTREME: 0.0,
        }.get(risk_level, 1.0)

        position_risk = base_risk * scale * risk_multiplier

        # Check portfolio-level risk constraint
        remaining_risk_budget = (self.capital * self.MAX_PORTFOLIO_RISK_PCT) - self.total_risk
        position_risk = min(position_risk, max(remaining_risk_budget, 0))

        # Check exposure constraint
        remaining_exposure = (self.capital * self.MAX_TOTAL_EXPOSURE_PCT) - self.total_exposure
        # Approximate: position_risk is the risk, size is larger
        estimated_size = position_risk * 20  # assume ~5% stop → 20x risk = notional
        estimated_size = min(estimated_size, max(remaining_exposure, 0))

        return round(max(estimated_size, 0), 2)

    # ------------------------------------------------------------------ #
    # Position Management                                                #
    # ------------------------------------------------------------------ #

    def can_open_position(self, asset: str) -> tuple[bool, str]:
        """Check if a new position can be opened for the given asset."""
        # Daily loss check
        if self.net_daily_pnl <= -self.DAILY_LOSS_LIMIT:
            return False, f"Daily loss limit reached (${abs(self.net_daily_pnl):.2f})"

        # Total exposure check
        if self.exposure_pct >= self.MAX_TOTAL_EXPOSURE_PCT:
            return False, f"Total exposure at {self.exposure_pct:.1%} (max {self.MAX_TOTAL_EXPOSURE_PCT:.1%})"

        # Per-asset check
        asset_counts = self.positions_by_asset()
        if asset_counts.get(asset, 0) >= self.MAX_SINGLE_ASSET_POSITIONS:
            return False, f"Max positions for {asset} reached ({self.MAX_SINGLE_ASSET_POSITIONS})"

        # Correlated positions check
        group = CORRELATION_GROUPS.get(asset, asset)
        group_counts = self.positions_by_correlation_group()
        if group_counts.get(group, 0) >= self.MAX_CORRELATED_POSITIONS:
            return False, f"Max correlated positions for {group} reached ({self.MAX_CORRELATED_POSITIONS})"

        return True, "OK"

    def open_position(self, position: Position) -> bool:
        """Add a new position. Returns False if limits prevent it."""
        can_open, reason = self.can_open_position(position.asset)
        if not can_open:
            logger.warning("Cannot open position: %s", reason)
            return False

        self.positions[position.position_id] = position
        self.daily_trades += 1
        logger.info(
            "Opened position %s: %s %s $%.2f",
            position.position_id[:8],
            position.direction.value,
            position.asset,
            position.size,
        )
        return True

    def close_position(self, position_id: str, realized_pnl: float) -> bool:
        """Close a position and record realized PnL."""
        pos = self.positions.pop(position_id, None)
        if pos is None:
            logger.warning("Position %s not found", position_id)
            return False

        self.daily_realized_pnl += realized_pnl
        self._closed_today.append({
            "position_id": position_id,
            "asset": pos.asset,
            "direction": pos.direction.value,
            "size": pos.size,
            "pnl": realized_pnl,
            "closed_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(
            "Closed position %s: PnL=$%.2f (daily=$%.2f)",
            position_id[:8], realized_pnl, self.daily_realized_pnl,
        )
        return True

    def update_unrealized_pnl(self, position_id: str, pnl: float) -> None:
        """Update mark-to-market PnL for an open position."""
        if position_id in self.positions:
            self.positions[position_id].unrealized_pnl = pnl

    # ------------------------------------------------------------------ #
    # Daily Reset                                                        #
    # ------------------------------------------------------------------ #

    def reset_daily(self) -> dict[str, Any]:
        """Reset daily counters. Call at start of trading day."""
        summary = {
            "date": self._last_reset.date().isoformat(),
            "realized_pnl": self.daily_realized_pnl,
            "trades": self.daily_trades,
            "closed_positions": len(self._closed_today),
        }
        self.daily_realized_pnl = 0.0
        self.daily_trades = 0
        self._closed_today.clear()
        self._last_reset = datetime.now(timezone.utc)
        logger.info("Daily reset complete: %s", summary)
        return summary

    # ------------------------------------------------------------------ #
    # Portfolio State                                                    #
    # ------------------------------------------------------------------ #

    def get_state(self) -> dict[str, Any]:
        """Full portfolio snapshot."""
        return {
            "capital": self.capital,
            "total_exposure": round(self.total_exposure, 2),
            "exposure_pct": round(self.exposure_pct, 4),
            "total_risk": round(self.total_risk, 2),
            "open_positions": self.open_position_count,
            "positions_by_asset": self.positions_by_asset(),
            "positions_by_group": self.positions_by_correlation_group(),
            "daily_realized_pnl": round(self.daily_realized_pnl, 2),
            "daily_unrealized_pnl": round(
                sum(p.unrealized_pnl for p in self.positions.values()), 2
            ),
            "net_daily_pnl": round(self.net_daily_pnl, 2),
            "daily_trades": self.daily_trades,
            "positions": [
                {
                    "id": pid,
                    "strategy_id": p.strategy_id,
                    "asset": p.asset,
                    "direction": p.direction.value,
                    "size": p.size,
                    "entry_price": p.entry_price,
                    "unrealized_pnl": p.unrealized_pnl,
                    "risk_amount": round(p.risk_amount, 2),
                }
                for pid, p in self.positions.items()
            ],
        }
