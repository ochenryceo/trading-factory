#!/usr/bin/env python3
"""Re-run all 30 DNAs through updated fast validation with confidence + queue + fail_reasons."""
import json
import sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.fast_validation.pass_fail import evaluate, calculate_confidence, generate_fail_reasons, generate_pass_checks
from services.fast_validation.queue_manager import classify_priority

# Load existing results (has the metrics from vectorbt runs)
fv_path = ROOT / "data" / "mock" / "fast_validation_results.json"
with open(fv_path) as f:
    results = json.load(f)

print(f"Loaded {len(results)} existing results")
print("=" * 60)

updated = []
for r in results:
    metrics = r.get("metrics", {})
    
    # Re-evaluate with new function signature
    status, reason, fail_reasons = evaluate(metrics)
    
    # Calculate confidence
    confidence = calculate_confidence(metrics)
    
    # Queue priority (only for PASS)
    queue_priority = classify_priority(confidence) if status == "PASS" else ""
    
    # Update result
    r["status"] = status
    r["reason"] = reason
    r["confidence"] = confidence
    r["queue_priority"] = queue_priority
    r["fail_reasons"] = fail_reasons
    
    updated.append(r)

# Save
with open(fv_path, "w") as f:
    json.dump(updated, f, indent=2)

# Stats
pass_count = sum(1 for r in updated if r["status"] == "PASS")
fail_count = len(updated) - pass_count

print(f"\n📊 PASS/FAIL COUNTS:")
print(f"  ✅ PASS: {pass_count}")
print(f"  ❌ FAIL: {fail_count}")
print(f"  📈 Pass Rate: {pass_count/len(updated)*100:.1f}%")

# Confidence distribution
confs = [r["confidence"] for r in updated]
high = sum(1 for c in confs if c >= 0.6)
mid = sum(1 for c in confs if 0.3 <= c < 0.6)
low = sum(1 for c in confs if c < 0.3)
avg = sum(confs) / len(confs)

print(f"\n🎯 CONFIDENCE DISTRIBUTION:")
print(f"  Average: {avg:.3f} ({avg*100:.1f}%)")
print(f"  High (≥0.6): {high}")
print(f"  Medium (0.3-0.6): {mid}")
print(f"  Low (<0.3): {low}")
print(f"  Min: {min(confs):.3f}")
print(f"  Max: {max(confs):.3f}")

# Queue allocation
queue = Counter()
for r in updated:
    if r["status"] == "PASS":
        queue[r["queue_priority"]] += 1
    else:
        queue["FAILED"] += 1

print(f"\n📋 QUEUE ALLOCATION:")
for priority in ["IMMEDIATE", "BATCH", "ARCHIVE", "FAILED"]:
    emoji = {"IMMEDIATE": "🔴", "BATCH": "🟡", "ARCHIVE": "⚫", "FAILED": "💀"}.get(priority, "")
    print(f"  {emoji} {priority}: {queue.get(priority, 0)}")

# Failure pattern analysis
print(f"\n💀 FAILURE PATTERNS:")
pattern_counts = Counter()
for r in updated:
    for fr in r.get("fail_reasons", []):
        frl = fr.lower()
        if "trade count" in frl:
            pattern_counts["trade_count"] += 1
        elif "drawdown" in frl:
            pattern_counts["drawdown"] += 1
        elif "pnl" in frl:
            pattern_counts["pnl"] += 1
        elif "win rate" in frl:
            pattern_counts["win_rate"] += 1

for pattern, count in pattern_counts.most_common():
    print(f"  {pattern}: {count} breaches")

print(f"\n✅ Updated {len(updated)} results saved to {fv_path}")
