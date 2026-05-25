from __future__ import annotations

import re
from typing import Any, Dict, Sequence, Tuple

from .config import (
    BUSINESS_WORDS,
    EXPIRED_WORDS,
    EXTERNAL_CITY_WORDS,
    ORDINARY_COMPLAINT_WORDS,
    PREPAID_WORDS,
    RUMOR_WORDS,
    RUNAWAY_WORDS,
)
from .utils import compact_text, contains_any, has_scene_context

def has_target_location(row: Dict[str, Any], target_city: str, target_province: str, districts: Sequence[str]) -> bool:
    text = f"{row.get('title','')} {row.get('content','')}"
    iplocation = str(row.get("iplocation") or "")
    targets = [target_city, target_city.replace("市", ""), *districts]
    if any(x and x in text for x in targets):
        return True
    if target_province and target_province in iplocation:
        return True
    if target_city and target_city.replace("市", "") in iplocation:
        return True
    return False


def mentions_target_in_text(row: Dict[str, Any], target_city: str, districts: Sequence[str]) -> bool:
    text = f"{row.get('title','')} {row.get('content','')}"
    targets = [target_city, target_city.replace("市", ""), *districts]
    return any(x and x in text for x in targets)


def mentions_external_city(row: Dict[str, Any], target_city: str) -> bool:
    text = f"{row.get('title','')} {row.get('content','')}"
    for city in EXTERNAL_CITY_WORDS:
        if city and city not in target_city and city in text:
            return True
    return False


def is_external_location(row: Dict[str, Any], target_city: str, target_province: str, districts: Sequence[str]) -> bool:
    iplocation = str(row.get("iplocation") or "")
    title = str(row.get("title") or "")
    title_targets = [target_city, target_city.replace("市", ""), *districts]
    leading_title = title[:120]
    if any(city and city not in target_city and city in leading_title for city in EXTERNAL_CITY_WORDS):
        if not any(x and x in leading_title for x in title_targets):
            return True
    if mentions_target_in_text(row, target_city, districts):
        return False
    if mentions_external_city(row, target_city):
        return True
    if iplocation and target_province and target_province not in iplocation:
        return True
    return False


def classify_risk(row: Dict[str, Any], target_city: str, target_province: str, districts: Sequence[str]) -> Tuple[str, str, bool, str]:
    text = f"{row.get('title','')} {row.get('content','')}"
    if is_external_location(row, target_city, target_province, districts):
        return "地域过滤", "剔除外市非辖区同类舆情", False, "地域过滤去重"

    has_prepaid = contains_any(text, PREPAID_WORDS)
    has_runaway = contains_any(text, RUNAWAY_WORDS)
    has_business = contains_any(text, BUSINESS_WORDS)
    has_location = has_target_location(row, target_city, target_province, districts)
    has_complaint_scene = contains_any(text, ["投诉", "消费保", "黑猫", "维权", "商家", "门店", "店铺", "经营者"])
    scene_context = has_scene_context(text)

    if has_location and scene_context:
        return "一级真实高风险负面", "重点预警，推送排查", True, ""
    if scene_context:
        return "一级真实高风险负面", "重点预警，推送排查", True, ""
    if has_runaway and has_business and contains_any(text, RUMOR_WORDS):
        return "五级不实传言", "标记存疑，人工复核", True, ""
    if contains_any(text, EXPIRED_WORDS):
        return "四级过期旧闻", "时效过滤剔除", False, "过期旧闻"
    if contains_any(text, ORDINARY_COMPLAINT_WORDS) and not has_runaway:
        return "二级普通消费", "直接过滤剔除", False, "普通消费纠纷"
    if has_runaway and not has_prepaid:
        return "三级无效水帖 / 吐槽", "直接过滤剔除", False, "未体现预充值办卡风险"
    return "三级无效水帖 / 吐槽", "直接过滤剔除", False, "不符合预充值跑路场景"


def extract_store(text: str) -> str:
    patterns = [
        r"[「『“\"]([\u4e00-\u9fffA-Za-z0-9·（）()]{2,40}(?:有限公司|信息技术有限公司|科技有限公司|公司|平台|APP|美容院|美容|美发店|理发店|健身房|健身|养生馆|洗浴中心|儿童乐园|早教|培训|瑜伽馆|舞蹈|游泳馆|口腔|医美|会所|门店|店铺|机构|商户))[」』”\"]",
        r"([\u4e00-\u9fffA-Za-z0-9·（）()]{2,40}(?:有限公司|信息技术有限公司|科技有限公司|公司|平台|APP|美容院|美容|美发店|理发店|健身房|健身|养生馆|洗浴中心|儿童乐园|早教|培训|瑜伽馆|舞蹈|游泳馆|口腔|医美|会所|门店|店铺|机构|商户))",
        r"(?:投诉对象|涉事门店|商家|店名|门店|收款方|平台|机构)[:：为是\s]*[「『“\"]?([\u4e00-\u9fffA-Za-z0-9·（）()]{2,40})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip(" ，,。；;：:")
    return ""


def extract_amount(text: str) -> str:
    match = re.search(r"(\d+(?:\.\d+)?\s*(?:万)?元)", text)
    return match.group(1).replace(" ", "") if match else ""


def extract_event(text: str) -> str:
    for word in RUNAWAY_WORDS:
        if word in text:
            return word
    return "预充值退款风险"


def extract_category(text: str) -> str:
    for word in BUSINESS_WORDS:
        if word in text:
            return word
    return "预付消费商户"


def extract_location(text: str, target_city: str, districts: Sequence[str]) -> str:
    for district in districts:
        if district and district in text:
            return district
    if target_city and target_city.replace("市", "") in text:
        return target_city
    match = re.search(r"([\u4e00-\u9fff]{2,8}(?:区|县|镇|街道|路|商场|广场|小区))", text)
    return match.group(1) if match else ""


def build_summary(row: Dict[str, Any], risk_level: str, target_city: str, districts: Sequence[str]) -> str:
    text = f"{row.get('title','')} {row.get('content','')}"
    store = extract_store(text) or compact_text(row.get("title"), 40)
    category = extract_category(text)
    location = extract_location(text, target_city, districts)
    event = extract_event(text)
    amount = extract_amount(text)
    source = row.get("source") or row.get("type") or ""
    pubtime = row.get("pubtime") or ""
    demand = "诉求退款/追回预存金额" if contains_any(text, ["退款", "退费", "追回", "退还", "维权"]) else "需属地核查预付卡风险"
    amount_text = f"，涉及{amount}" if amount else ""
    location_text = f"{location}" if location else "辖区待核"
    return f"{store}（{category}，{location_text}）出现{event}{amount_text}，{demand}。来源：{source}，发布时间：{pubtime}，等级：{risk_level}。"
