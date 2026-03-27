"""Fast validation result schema."""
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List


@dataclass
class FastValidationResult:
    strategy_id: str
    status: str  # "PASS" or "FAIL"
    reason: Optional[str] = None
    metrics: Dict = field(default_factory=dict)
    tested_window: str = ""  # e.g. "2026-02-20 to 2026-03-20"
    confidence: float = 0.0  # Weighted confidence score 0.0-1.0
    queue_priority: str = ""  # IMMEDIATE / BATCH / ARCHIVE
    fail_reasons: List[str] = field(default_factory=list)  # Detailed failure reasons

    def to_dict(self) -> dict:
        return asdict(self)
