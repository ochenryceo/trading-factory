"""
Darwin Ranking — Rank strategies by composite score.

Score = Sharpe * 0.3 + win_rate * 0.2 + (1 - max_dd) * 0.3 + profit_factor * 0.2
"""

from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import List

from .backtester import BacktestResult


@dataclass
class RankedStrategy:
    rank: int
    strategy_code: str
    composite_score: float
    sharpe_component: float
    winrate_component: float
    drawdown_component: float
    pf_component: float
    metrics: BacktestResult

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def compute_composite_score(result: BacktestResult) -> float:
    """
    Compute composite score:
      Sharpe * 0.3 + win_rate * 0.2 + (1 - max_dd) * 0.3 + profit_factor * 0.2

    Normalizations:
      - Sharpe: clip to [-2, 4], normalize to [0, 1]
      - Win rate: already [0, 1]
      - Max DD: already [0, 1], use (1 - max_dd)
      - Profit factor: clip to [0, 5], normalize to [0, 1]
    """
    # Normalize Sharpe to [0, 1] range
    sharpe_norm = max(0, min(1, (result.sharpe_ratio + 2) / 6))

    # Win rate already in [0, 1]
    wr_norm = max(0, min(1, result.win_rate))

    # Drawdown component: 1 - max_dd (lower DD = higher score)
    dd_norm = max(0, min(1, 1 - result.max_drawdown))

    # Profit factor normalized to [0, 1]
    pf_norm = max(0, min(1, result.profit_factor / 5))

    score = (
        sharpe_norm * 0.3 +
        wr_norm * 0.2 +
        dd_norm * 0.3 +
        pf_norm * 0.2
    )

    return round(score, 6)


def rank_strategies(results: List[BacktestResult]) -> List[RankedStrategy]:
    """
    Rank a list of BacktestResults by composite score (descending).
    """
    scored = []
    for r in results:
        sharpe_norm = max(0, min(1, (r.sharpe_ratio + 2) / 6))
        wr_norm = max(0, min(1, r.win_rate))
        dd_norm = max(0, min(1, 1 - r.max_drawdown))
        pf_norm = max(0, min(1, r.profit_factor / 5))

        score = compute_composite_score(r)

        scored.append(RankedStrategy(
            rank=0,
            strategy_code=r.strategy_code,
            composite_score=score,
            sharpe_component=round(sharpe_norm * 0.3, 4),
            winrate_component=round(wr_norm * 0.2, 4),
            drawdown_component=round(dd_norm * 0.3, 4),
            pf_component=round(pf_norm * 0.2, 4),
            metrics=r,
        ))

    # Sort descending
    scored.sort(key=lambda x: x.composite_score, reverse=True)

    # Assign ranks
    for i, s in enumerate(scored):
        s.rank = i + 1

    return scored
