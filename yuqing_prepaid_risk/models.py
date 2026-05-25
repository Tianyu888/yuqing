from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

@dataclass
class ProcessedItem:
    row: Dict[str, Any]
    risk_level: str
    risk_label: str
    risk_summary: str
    dedup_key: str
    dedup_reason: str
    keep: bool
    filter_reason: str = ""
    model_used: str = "否"
    model_reason: str = ""
