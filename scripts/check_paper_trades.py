#!/usr/bin/env python3
"""Check paper trading status — webhook signals vs expectations."""
import json
from pathlib import Path
from datetime import datetime, timezone

DATA = Path(__file__).resolve().parents[1] / "data"
PT_PATH = DATA / "production" / "paper_trades.jsonl"

# Paper test started March 23, 2026
PAPER_START = datetime(2026, 3, 23, tzinfo=timezone.utc)
# Expected: ~1-3 trades per month on daily bars (RSI oversold + BB touch is rare)
EXPECTED_MONTHLY_TRADES = (1, 3)

# TradingView backtest reference (2010-2026)
TV_REFERENCE = {
    "trades": 26,
    "years": 16,
    "trades_per_year": 26 / 16,  # ~1.6/year
    "win_rate": 0.5769,
    "return_pct": 26.13,
    "profit_factor": 2.085,
    "max_dd": 0.06,
}

def check():
    now = datetime.now(timezone.utc)
    days_running = (now - PAPER_START).days
    
    print(f"📈 PAPER TRADING STATUS — LOCKED_PRODUCTION_V1")
    print(f"   Started: {PAPER_START.strftime('%Y-%m-%d')}")
    print(f"   Running: {days_running} days")
    print(f"   Expected trades: ~{TV_REFERENCE['trades_per_year']:.1f}/year ({TV_REFERENCE['trades_per_year']/12:.1f}/month)")
    print()
    
    trades = []
    if PT_PATH.exists():
        with open(PT_PATH) as f:
            for line in f:
                try:
                    trades.append(json.loads(line.strip()))
                except:
                    pass
    
    entries = [t for t in trades if t.get("type") == "ENTRY"]
    exits = [t for t in trades if t.get("type") == "EXIT"]
    
    if not trades:
        expected_in_period = TV_REFERENCE["trades_per_year"] * days_running / 365
        print(f"   Status: No webhook signals received yet")
        print(f"   Expected in {days_running} days: ~{expected_in_period:.1f} trades")
        if expected_in_period < 0.5:
            print(f"   ✅ Normal — strategy fires rarely on daily bars")
        else:
            print(f"   ⚠️ May be overdue — check TradingView chart for missed signals")
    else:
        print(f"   Total signals: {len(trades)}")
        print(f"   Entries: {len(entries)} | Exits: {len(exits)}")
        
        wins = sum(1 for t in trades if t.get("pnl_pct", 0) > 0)
        if entries:
            paper_wr = wins / len(entries) if entries else 0
            print(f"   Paper WR: {paper_wr:.0%} (backtest: {TV_REFERENCE['win_rate']:.0%})")
            
            divergence = abs(paper_wr - TV_REFERENCE["win_rate"]) * 100
            if divergence > 15:
                print(f"   🚨 WR divergence: {divergence:.0f}pp from backtest")
            else:
                print(f"   ✅ WR within expected range")
        
        print(f"\n   Recent trades:")
        for t in trades[-5:]:
            print(f"     {t.get('action','?').upper():5s} {t.get('ticker','')} @ ${t.get('price',0):,.2f} — {t.get('received_at','')[:19]}")
    
    print(f"\n   Reference (TradingView backtest 2010-2026):")
    print(f"     Trades: {TV_REFERENCE['trades']} | WR: {TV_REFERENCE['win_rate']:.0%} | PF: {TV_REFERENCE['profit_factor']:.2f} | Ret: +{TV_REFERENCE['return_pct']:.1f}% | DD: {TV_REFERENCE['max_dd']:.0%}")

if __name__ == "__main__":
    check()
