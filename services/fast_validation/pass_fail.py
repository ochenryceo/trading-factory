"""Pass/fail gate for fast validation metrics — with confidence scoring & detailed fail reasons."""
from typing import Dict, Tuple, Optional, List

FAST_VALIDATION_RULES = {
    "min_trades": 10,
    "max_drawdown": 0.12,
    "min_pnl": -5000,      # Allow modest losses on short windows
    "min_win_rate": 0.30,
}


def calculate_confidence(metrics: Dict) -> float:
    """Weighted confidence score 0.0 to 1.0"""
    sharpe_score = min(max(metrics.get('sharpe_ratio', metrics.get('sharpe', 0)) / 2.0, 0), 1)
    wr_score = min(max(metrics.get('win_rate', 0), 0), 1)
    dd_score = min(max(1 - metrics.get('max_drawdown', 1) / 0.2, 0), 1)
    trade_score = min(max(metrics.get('trade_count', 0) / 100, 0), 1)

    confidence = (
        sharpe_score * 0.3 +
        wr_score * 0.25 +
        dd_score * 0.25 +
        trade_score * 0.2
    )
    return round(confidence, 3)


def generate_fail_reasons(metrics: Dict, rules: Optional[Dict] = None) -> List[str]:
    """Generate specific, human-readable failure reasons."""
    r = rules or FAST_VALIDATION_RULES
    reasons = []

    trade_count = metrics.get("trade_count", 0)
    if trade_count < r["min_trades"]:
        reasons.append(f"❌ Trade count: {trade_count} (min: {r['min_trades']})")

    max_dd = metrics.get("max_drawdown", 1.0)
    if max_dd > r["max_drawdown"]:
        reasons.append(f"❌ Drawdown: {max_dd:.1%} (max: {r['max_drawdown']:.1%})")

    pnl = metrics.get("total_pnl", 0)
    if pnl < r["min_pnl"]:
        reasons.append(f"❌ PnL: ${pnl:.2f} (min: ${r['min_pnl']})")

    win_rate = metrics.get("win_rate", 0)
    if win_rate < r["min_win_rate"]:
        reasons.append(f"❌ Win rate: {win_rate:.1%} (min: {r['min_win_rate']:.1%})")

    return reasons


def generate_pass_checks(metrics: Dict, rules: Optional[Dict] = None) -> List[str]:
    """Generate check results for ALL thresholds — green for met, red for breached."""
    r = rules or FAST_VALIDATION_RULES
    checks = []

    trade_count = metrics.get("trade_count", 0)
    if trade_count >= r["min_trades"]:
        checks.append(f"✅ Trade count: {trade_count} (min: {r['min_trades']})")
    else:
        checks.append(f"❌ Trade count: {trade_count} (min: {r['min_trades']})")

    max_dd = metrics.get("max_drawdown", 1.0)
    if max_dd <= r["max_drawdown"]:
        checks.append(f"✅ Drawdown: {max_dd:.1%} (max: {r['max_drawdown']:.1%})")
    else:
        checks.append(f"❌ Drawdown: {max_dd:.1%} (max: {r['max_drawdown']:.1%})")

    pnl = metrics.get("total_pnl", 0)
    if pnl >= r["min_pnl"]:
        checks.append(f"✅ PnL: ${pnl:.2f} (min: ${r['min_pnl']})")
    else:
        checks.append(f"❌ PnL: ${pnl:.2f} (min: ${r['min_pnl']})")

    win_rate = metrics.get("win_rate", 0)
    if win_rate >= r["min_win_rate"]:
        checks.append(f"✅ Win rate: {win_rate:.1%} (min: {r['min_win_rate']:.1%})")
    else:
        checks.append(f"❌ Win rate: {win_rate:.1%} (min: {r['min_win_rate']:.1%})")

    return checks


def evaluate(metrics: Dict, rules: Optional[Dict] = None) -> Tuple[str, Optional[str], List[str]]:
    """
    Evaluate metrics against thresholds.

    Returns
    -------
    (status, reason, fail_reasons) — ("PASS", None, []) or ("FAIL", "reason string", ["❌ ..."])
    """
    r = rules or FAST_VALIDATION_RULES
    fail_reasons = generate_fail_reasons(metrics, r)

    if fail_reasons:
        # Legacy reason string for backward compat
        legacy_parts = []
        tc = metrics.get("trade_count", 0)
        if tc < r["min_trades"]:
            legacy_parts.append(f"trade_count {tc} < min {r['min_trades']}")
        dd = metrics.get("max_drawdown", 1.0)
        if dd > r["max_drawdown"]:
            legacy_parts.append(f"max_drawdown {dd:.4f} > max {r['max_drawdown']}")
        pnl = metrics.get("total_pnl", 0)
        if pnl < r["min_pnl"]:
            legacy_parts.append(f"total_pnl {pnl:.4f} < min {r['min_pnl']}")
        wr = metrics.get("win_rate", 0)
        if wr < r["min_win_rate"]:
            legacy_parts.append(f"win_rate {wr:.4f} < min {r['min_win_rate']}")
        return "FAIL", "; ".join(legacy_parts), fail_reasons
    return "PASS", None, []
