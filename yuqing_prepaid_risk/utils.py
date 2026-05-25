from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Sequence

from .config import BUSINESS_WORDS, PREPAID_WORDS, RUNAWAY_WORDS

def log(message: str) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {message}", flush=True)


def norm_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "", text)
    return text.lower()


def compact_text(value: Any, max_len: int = 260) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


def contains_any(text: str, words: Sequence[str]) -> bool:
    return any(word in text for word in words)


def has_scene_context(text: str) -> bool:
    chunks = re.split(r"[。！？!?；;\n\r]", text)
    if not chunks:
        chunks = [text]
    title_like = text[:160]
    for chunk in [title_like, *chunks]:
        if len(chunk) > 260:
            continue
        has_prepaid = contains_any(chunk, PREPAID_WORDS)
        has_runaway = contains_any(chunk, RUNAWAY_WORDS)
        has_business = contains_any(chunk, BUSINESS_WORDS)
        has_complaint = contains_any(chunk, ["投诉", "消费保", "黑猫", "维权", "商家", "门店", "店铺", "经营者"])
        if has_prepaid and has_runaway and (has_business or has_complaint):
            return True
    return False
