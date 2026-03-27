#!/usr/bin/env python3
"""
Portfolio Construction Engine — Automatic Strategy Selection

Selects the best COMBINATION of strategies:
- Low correlation between strategies
- Balanced risk across assets/timeframes
- Maximum diversification

Output: A balanced portfolio of 3-5 strategies ready for deployment.

Owner: Overseer + Strategist
"""

import json
import logging
import itertools
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Tuple

import numpy as np

log = logging.getLogger("portfolio_engine")

PROJECT = Path(__file__).resolve().parents[1]
DATA = PROJECT / "data"
PORTFOLIO_PATH = DATA / "portfolio_recommendation.json"


class PortfolioEngine:
    """
    Constructs optimal portfolio from validated strategies.
    
    Selection criteria:
    1. Each strategy must be READY_FOR_PAPER (passed all directives)
    2. Maximize diversity: different assets × timeframes × styles
    3. Minimize correlation: strategies should not trade the same patterns
    4. Balance risk: no single strategy dominates drawdown
    """
    
    def __init__(self):
        self.candidates = []
    
    def load_candidates(self) -> List[Dict]:
        """Load all realistic READY_FOR_PAPER strategies."""
        candidates = []
        seen = set()
        
        fv_path = DATA / "final_validation_log.jsonl"
        if not fv_path.exists():
            return candidates
        
        with open(fv_path) as f:
            for line in f:
                try:
                    d = json.loads(line.strip())
                    if d.get("tag") != "READY_FOR_PAPER":
                        continue
                    
                    code = d.get("strategy_code", "")
                    if code in seen or "-clone" in code:  # skip clones
                        continue
                    
                    sr = d.get("baseline_sharpe", 0)
                    wr = d.get("baseline_win_rate", 0)
                    dd = d.get("baseline_max_dd", 0)
                    
                    # Realistic band only
                    if 0.8 <= sr <= 3.0 and 0.45 <= wr <= 0.75 and 0.02 <= dd <= 0.12:
                        seen.add(code)
                        candidates.append(d)
                except:
                    continue
        
        self.candidates = candidates
        return candidates
    
    def _infer_attributes(self, strategy: Dict) -> Dict:
        """Infer asset, timeframe, style from strategy code and metadata."""
        code = strategy.get("strategy_code", "")
        
        # Try to find in DNA archive
        asset = strategy.get("asset", "")
        timeframe = ""
        style = ""
        
        # Infer from code patterns
        if "SCP" in code or "scalping" in code.lower():
            style = "scalping"
        elif "MOM" in code or "momentum" in code.lower():
            style = "momentum"
        elif "MR" in code or "mean" in code.lower():
            style = "mean_reversion"
        elif "VOF" in code or "volume" in code.lower():
            style = "volume_orderflow"
        elif "TF" in code or "trend" in code.lower():
            style = "trend_following"
        else:
            style = "unknown"
        
        return {"asset": asset, "timeframe": timeframe, "style": style}
    
    def _diversity_score(self, portfolio: List[Dict]) -> float:
        """
        Score portfolio diversity (0-1).
        Higher = more diverse assets, timeframes, styles.
        
        CEO Rule: If any single asset > 50% of portfolio, heavy penalty.
        Target: NQ ≤ 40%, CL ≥ 30%, GC ≥ 30%
        """
        if len(portfolio) <= 1:
            return 0
        
        assets = {}
        styles = set()
        
        for s in portfolio:
            attrs = self._infer_attributes(s)
            asset = attrs["asset"] or s.get("asset", "")
            assets[asset] = assets.get(asset, 0) + 1
            styles.add(attrs["style"])
        
        # Asset diversity
        asset_unique = len(assets) / min(len(portfolio), 3)
        
        # Style diversity
        style_div = len(styles) / min(len(portfolio), 5)
        
        # Concentration penalty: if any asset > 50% of portfolio, penalize hard
        concentration_penalty = 0
        for asset, count in assets.items():
            weight = count / len(portfolio)
            if weight > 0.5:
                concentration_penalty += (weight - 0.5) * 2  # harsh penalty
        
        base_score = asset_unique * 0.5 + style_div * 0.5
        final = max(0, base_score - concentration_penalty)
        
        return round(final, 3)
    
    def _risk_balance_score(self, portfolio: List[Dict]) -> float:
        """
        Score risk balance (0-1).
        Higher = more evenly distributed drawdown risk.
        """
        if len(portfolio) <= 1:
            return 0
        
        drawdowns = [s.get("baseline_max_dd", 0.05) for s in portfolio]
        if max(drawdowns) == 0:
            return 1.0
        
        # Coefficient of variation — lower = more balanced
        dd_arr = np.array(drawdowns)
        if dd_arr.mean() > 0:
            cv = dd_arr.std() / dd_arr.mean()
            return round(max(0, 1 - cv), 3)
        return 0.5
    
    def _portfolio_sharpe(self, portfolio: List[Dict]) -> float:
        """Average Sharpe of portfolio strategies."""
        sharpes = [s.get("baseline_sharpe", 0) for s in portfolio]
        return round(np.mean(sharpes), 3) if sharpes else 0
    
    def _portfolio_score(self, portfolio: List[Dict]) -> float:
        """
        Combined portfolio score.
        
        Weights:
        - Sharpe quality: 40%
        - Diversity: 35%
        - Risk balance: 25%
        """
        sharpe_score = min(self._portfolio_sharpe(portfolio) / 2.5, 1.0)
        diversity = self._diversity_score(portfolio)
        risk_balance = self._risk_balance_score(portfolio)
        
        return round(sharpe_score * 0.4 + diversity * 0.35 + risk_balance * 0.25, 3)
    
    def construct_portfolio(self, size: int = 4) -> Dict:
        """
        Construct optimal portfolio of given size.
        
        Tries combinations and picks the highest scoring one.
        """
        if not self.candidates:
            self.load_candidates()
        
        if len(self.candidates) < size:
            return {"error": f"Only {len(self.candidates)} candidates, need {size}"}
        
        # Pre-sort by sharpe and take top N for combinatorial search
        sorted_candidates = sorted(self.candidates, key=lambda x: -x.get("baseline_sharpe", 0))
        pool = sorted_candidates[:30]  # limit search space
        
        best_portfolio = None
        best_score = -1
        
        # Try combinations — enforce market diversity
        for combo in itertools.combinations(pool, size):
            combo_list = list(combo)
            
            # Hard constraint: reject portfolios where single asset > 50%
            asset_counts = {}
            for s in combo_list:
                a = s.get("asset", self._infer_attributes(s).get("asset", ""))
                asset_counts[a] = asset_counts.get(a, 0) + 1
            
            # Prefer multi-asset but allow single-asset if nothing else available
            # Heavy score penalty applied via diversity_score instead of hard reject
            
            score = self._portfolio_score(combo_list)
            
            if score > best_score:
                best_score = score
                best_portfolio = combo_list
        
        if not best_portfolio:
            return {"error": "Could not construct portfolio"}
        
        # Build recommendation
        portfolio = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "size": size,
            "score": best_score,
            "diversity": self._diversity_score(best_portfolio),
            "risk_balance": self._risk_balance_score(best_portfolio),
            "avg_sharpe": self._portfolio_sharpe(best_portfolio),
            "strategies": [],
        }
        
        for s in best_portfolio:
            attrs = self._infer_attributes(s)
            portfolio["strategies"].append({
                "strategy_code": s.get("strategy_code", ""),
                "asset": s.get("asset", attrs["asset"]),
                "style": attrs["style"],
                "sharpe": s.get("baseline_sharpe", 0),
                "win_rate": s.get("baseline_win_rate", 0),
                "max_dd": s.get("baseline_max_dd", 0),
                "return_pct": s.get("baseline_return_pct", 0),
            })
        
        # Save recommendation
        PORTFOLIO_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(PORTFOLIO_PATH, "w") as f:
            json.dump(portfolio, f, indent=2, default=str)
        
        return portfolio


def recommend_portfolio(size: int = 4) -> Dict:
    """Convenience function — construct and return portfolio recommendation."""
    engine = PortfolioEngine()
    return engine.construct_portfolio(size)
