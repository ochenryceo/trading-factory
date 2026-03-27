#!/usr/bin/env python3
"""Daily report generator — posts to Discord via webhook."""
import json
from pathlib import Path
from datetime import datetime, timezone

DATA = Path(__file__).resolve().parents[1] / "data"

def generate_report() -> str:
    lines = [f"📊 **DAILY FACTORY REPORT — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}**\n"]
    
    # Factory stats
    lb_path = DATA / "continuous_leaderboard.json"
    if lb_path.exists():
        with open(lb_path) as f:
            lb = json.load(f)
        lines.append(f"**🏭 Factory:** Gen {lb.get('generation',0)} | {lb.get('total_tested',0):,} tested | {lb.get('total_passed',0)} Darwin pass | {lb.get('total_paper_ready',0)} paper ready")
    
    # Validation results
    fv_tags = {}
    fv_path = DATA / "final_validation_log.jsonl"
    if fv_path.exists():
        with open(fv_path) as f:
            for line in f:
                try:
                    d = json.loads(line.strip())
                    tag = d.get("tag", "?")
                    fv_tags[tag] = fv_tags.get(tag, 0) + 1
                except:
                    pass
        lines.append(f"\n**⚙️ Validation Pipeline:**")
        lines.append(f"  🟢 Ready for paper: {fv_tags.get('READY_FOR_PAPER', 0)}")
        lines.append(f"  🟡 Suspicious: {fv_tags.get('READY_FOR_PAPER_SUSPICIOUS', 0)}")
        lines.append(f"  🟡 Needs hardening: {fv_tags.get('REQUIRES_HARDENING', 0)}")
        lines.append(f"  🔴 Rejected: {fv_tags.get('REJECTED_POST_DARWIN', 0)}")
    
    # Paper trading
    pt_path = DATA / "production" / "paper_trades.jsonl"
    trades = []
    if pt_path.exists():
        with open(pt_path) as f:
            for line in f:
                try:
                    trades.append(json.loads(line.strip()))
                except:
                    pass
    if trades:
        lines.append(f"\n**📈 Paper Trading:** {len(trades)} signals received")
        last = trades[-1]
        lines.append(f"  Last: {last.get('action','?').upper()} {last.get('ticker','')} @ ${last.get('price',0):,.2f}")
    else:
        lines.append(f"\n**📈 Paper Trading:** Waiting for first signal (daily bars, ~1-3/month)")
    
    # Failure intelligence
    fp_path = DATA / "failure_patterns.json"
    if fp_path.exists():
        with open(fp_path) as f:
            fp = json.load(f)
        top = list(fp.get("patterns", {}).items())[:3]
        if top:
            lines.append(f"\n**🧠 Top Failure Patterns:**")
            for pat, count in top:
                lines.append(f"  {pat}: {count}")
    
    return "\n".join(lines)

if __name__ == "__main__":
    print(generate_report())
