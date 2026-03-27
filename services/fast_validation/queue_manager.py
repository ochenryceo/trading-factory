"""Smart queue manager for strategy prioritization based on confidence scores."""
from typing import Dict, List, Any

QUEUE_THRESHOLDS = {
    "immediate": 0.7,   # confidence > 0.7 → run Darwin immediately
    "batch": 0.4,       # confidence 0.4-0.7 → queue for next batch
    "archive": 0.0      # confidence < 0.4 → archive, don't waste compute
}


def classify_priority(confidence: float) -> str:
    """Classify a strategy's queue priority based on confidence score."""
    if confidence >= QUEUE_THRESHOLDS["immediate"]:
        return "IMMEDIATE"
    elif confidence >= QUEUE_THRESHOLDS["batch"]:
        return "BATCH"
    else:
        return "ARCHIVE"


def get_queue_state(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Get current queue state from a list of validation results.
    
    Returns queue summary with counts and strategy lists per priority.
    """
    queue = {
        "IMMEDIATE": [],
        "BATCH": [],
        "ARCHIVE": [],
        "FAILED": [],
    }

    for r in results:
        if r.get("status") == "FAIL":
            queue["FAILED"].append(r["strategy_id"])
        else:
            priority = r.get("queue_priority", classify_priority(r.get("confidence", 0)))
            if priority in queue:
                queue[priority].append(r["strategy_id"])
            else:
                queue["ARCHIVE"].append(r["strategy_id"])

    return {
        "immediate": {
            "count": len(queue["IMMEDIATE"]),
            "strategies": queue["IMMEDIATE"],
        },
        "batch": {
            "count": len(queue["BATCH"]),
            "strategies": queue["BATCH"],
        },
        "archive": {
            "count": len(queue["ARCHIVE"]),
            "strategies": queue["ARCHIVE"],
        },
        "failed": {
            "count": len(queue["FAILED"]),
            "strategies": queue["FAILED"],
        },
        "total_passed": len(queue["IMMEDIATE"]) + len(queue["BATCH"]) + len(queue["ARCHIVE"]),
        "total_failed": len(queue["FAILED"]),
    }
