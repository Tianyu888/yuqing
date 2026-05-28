from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Sequence

from .config import BUSINESS_WORDS, IRRELEVANT_CRIME_WORDS, IRRELEVANT_NEGATION_PHRASES, PREPAID_WORDS, RUNAWAY_WORDS

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


def has_irrelevant_crime_context(text: str) -> bool:
    has_crime = contains_any(text, IRRELEVANT_CRIME_WORDS)
    if not has_crime:
        return False
    if contains_any(text, IRRELEVANT_NEGATION_PHRASES):
        return True
    has_consumer_scene = contains_any(text, ["投诉", "消费保", "黑猫", "维权", "退款", "退费", "会员卡", "储值卡", "课包"])
    return not has_consumer_scene


def has_unrelated_risk_negation(text: str) -> bool:
    negated = contains_any(
        text,
        [
            "无关",
            "不属于",
            "非预充值",
            "不是预充值",
            "不涉及商户跑路",
            "未明确预充值卡风险",
            "无具体商户跑路",
            "无闭店失联",
            "无拒不退款",
        ],
    )
    if not negated:
        return False
    risk_domain = contains_any(text, ["预充值", "预付消费", "商户跑路", "闭店", "失联", "拒不退款"])
    return risk_domain
