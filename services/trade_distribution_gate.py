"""
Trade Distribution Gate — ensures PnL isn't concentrated in time or single trades.
"""
from typing import List, Dict
from collections import defaultdict


def gini_coefficient(pnls: List[float]) -> float:
    """Gini coefficient of PnL distribution. 0=equal, 1=concentrated."""
    pnls_abs = sorted([abs(p) for p in pnls])
    n = len(pnls_abs)
    if n == 0 or sum(pnls_abs) == 0:
        return 0.0
    cumulative = 0.0
    weighted_sum = 0.0
    for i, val in enumerate(pnls_abs):
        cumulative += val
        weighted_sum += (i + 1) * val
    return (2 * weighted_sum) / (n * cumulative) - (n + 1) / n


def check_trade_distribution(trade_log: List[Dict], total_pnl: float) -> dict:
    """
    Check trade distribution for concentration risk.
    
    Rules:
    - No single calendar month > 30% of total PnL
    - No single trade > 15% of total PnL  
    - PnL must span at least 3 calendar years
    - Gini coefficient < 0.6
    
    Returns dict with passed, conditional, failure details.
    """
    if not trade_log or total_pnl <= 0:
        return {"passed": False, "conditional": False, "failure_tag": "FAIL_TRADE_DISTRIBUTION", 
                "reason": "No profitable trades",
                "max_month_pnl_pct": 0.0, "max_trade_pnl_pct": 0.0,
                "years_with_pnl": 0, "gini": 0.0}
    
    # Group PnL by month
    monthly_pnl = defaultdict(float)
    yearly_pnl = defaultdict(float)
    max_trade_pnl_pct = 0.0
    all_pnls = []
    
    for t in trade_log:
        pnl = t.get("pnl_pct", 0)
        all_pnls.append(pnl)
        entry_time = t.get("entry_time", "")
        if len(entry_time) >= 7:
            month_key = entry_time[:7]  # "YYYY-MM"
            year_key = entry_time[:4]   # "YYYY"
            monthly_pnl[month_key] += pnl
            yearly_pnl[year_key] += pnl
        
        # Single trade concentration
        if total_pnl > 0:
            trade_pct = abs(pnl) / total_pnl * 100
            max_trade_pnl_pct = max(max_trade_pnl_pct, trade_pct)
    
    # Max month concentration
    max_month_pnl_pct = 0.0
    if monthly_pnl and total_pnl > 0:
        max_month_val = max(monthly_pnl.values())
        max_month_pnl_pct = max_month_val / total_pnl * 100
    
    years_with_pnl = len([y for y, p in yearly_pnl.items() if p > 0])
    
    # Gini coefficient
    gini = gini_coefficient(all_pnls) if all_pnls else 0.0
    
    # Determine pass/conditional/fail
    reasons = []
    hard_fail = False
    soft_fail = False
    
    if max_month_pnl_pct > 40:
        hard_fail = True
        reasons.append(f"Month concentration {max_month_pnl_pct:.0f}% > 40%")
    elif max_month_pnl_pct > 30:
        soft_fail = True
        reasons.append(f"Month concentration {max_month_pnl_pct:.0f}% > 30%")
    
    if max_trade_pnl_pct > 20:
        hard_fail = True
        reasons.append(f"Single trade {max_trade_pnl_pct:.0f}% > 20% of PnL")
    elif max_trade_pnl_pct > 15:
        soft_fail = True
        reasons.append(f"Single trade {max_trade_pnl_pct:.0f}% > 15% of PnL")
    
    if years_with_pnl < 3:
        hard_fail = True
        reasons.append(f"Only {years_with_pnl} profitable years (need 3+)")
    
    # Gini checks
    if gini > 0.6:
        hard_fail = True
        reasons.append(f"Gini {gini:.2f} > 0.6 (PnL too concentrated)")
    elif gini > 0.5:
        soft_fail = True
        reasons.append(f"Gini {gini:.2f} > 0.5 (PnL moderately concentrated)")
    
    passed = not hard_fail and not soft_fail
    conditional = soft_fail and not hard_fail
    
    return {
        "passed": passed,
        "conditional": conditional,
        "max_month_pnl_pct": round(max_month_pnl_pct, 1),
        "max_trade_pnl_pct": round(max_trade_pnl_pct, 1),
        "years_with_pnl": years_with_pnl,
        "gini": round(gini, 4),
        "failure_tag": "FAIL_TRADE_DISTRIBUTION" if hard_fail else ("CONDITIONAL_TRADE_DISTRIBUTION" if conditional else None),
        "reasons": reasons,
    }
