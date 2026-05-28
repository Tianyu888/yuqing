from __future__ import annotations

import re
from typing import Any, Dict, Optional, Sequence, Tuple

from .config import (
    BUSINESS_WORDS,
    EXPIRED_WORDS,
    EXTERNAL_CITY_WORDS,
    ORDINARY_COMPLAINT_WORDS,
    PREPAID_WORDS,
    RUMOR_WORDS,
    RUNAWAY_WORDS,
)
from .utils import compact_text, contains_any, has_irrelevant_crime_context, has_scene_context, has_unrelated_risk_negation

def location_targets(target_city: str, districts: Sequence[str]) -> Sequence[str]:
    targets = [target_city, target_city.replace("市", ""), *districts]
    for district in districts:
        if len(district) > 2 and district.endswith(("市", "区", "县")):
            targets.append(district[:-1])
    return [x for x in targets if x]


def has_target_location(row: Dict[str, Any], target_city: str, target_province: str, districts: Sequence[str]) -> bool:
    text = f"{row.get('title','')} {row.get('content','')}"
    iplocation = str(row.get("iplocation") or "")
    targets = location_targets(target_city, districts)
    if any(x and x in text for x in targets):
        return True
    if target_province and target_province in iplocation:
        return True
    if target_city and target_city.replace("市", "") in iplocation:
        return True
    return False


def mentions_target_in_text(row: Dict[str, Any], target_city: str, districts: Sequence[str]) -> bool:
    text = f"{row.get('title','')} {row.get('content','')}"
    targets = location_targets(target_city, districts)
    return any(x and x in text for x in targets)


def mentions_external_city(row: Dict[str, Any], target_city: str) -> bool:
    text = f"{row.get('title','')} {row.get('content','')}"
    for city in EXTERNAL_CITY_WORDS:
        if city and city not in target_city and city in text:
            return True
    return False


def is_external_location(row: Dict[str, Any], target_city: str, target_province: str, districts: Sequence[str]) -> Optional[bool]:
    """三态返回：True=确认外部, False=确认目标城市, None=不确定（需LLM复核）"""
    iplocation = str(row.get("iplocation") or "")
    title = str(row.get("title") or "")
    title_targets = location_targets(target_city, districts)
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
    if not iplocation:
        return None
    # IP匹配目标省份但正文无明确目标城市提及 → 不确定
    return None


def classify_risk(row: Dict[str, Any], target_city: str, target_province: str, districts: Sequence[str]) -> Tuple[str, str, bool, str]:
    text = f"{row.get('title','')} {row.get('content','')}"
    location_status = is_external_location(row, target_city, target_province, districts)
    if location_status is True:
        return "地域过滤", "剔除外市非辖区同类舆情", False, "地域过滤去重"
    if location_status is None:
        return "地域待定", "需大模型复核是否属地", False, "地域待定"

    has_prepaid = contains_any(text, PREPAID_WORDS)
    has_runaway = contains_any(text, RUNAWAY_WORDS)
    has_business = contains_any(text, BUSINESS_WORDS)
    has_location = has_target_location(row, target_city, target_province, districts)
    has_complaint_scene = contains_any(text, ["投诉", "消费保", "黑猫", "维权", "商家", "门店", "店铺", "经营者"])
    scene_context = has_scene_context(text)

    if has_unrelated_risk_negation(text):
        return "三级无效水帖 / 吐槽", "直接过滤剔除", False, "与预充值商户跑路风险无关"
    if has_irrelevant_crime_context(text):
        return "三级无效水帖 / 吐槽", "直接过滤剔除", False, "刑案犯罪史等无关舆情"
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





GENERIC_PREFIXES = re.compile(r"^(知名|大型|连锁|多家|某|这家|本地|全国|老牌|新型|传统|小型|大型连锁|民营|私人|公办)")
_SENT_SPLIT = re.compile(r"[。！？；\n]")
_CONNECTOR_CHARS = set("的在被从到于有为对与及以因让向往申请提供退还关闭撤销开设经营停止中断终止违约违法违规被罚罚款处罚停业歇业吊销注销破产清盘清算")

def _is_valid_store_name(name: str) -> bool:
    """验证提取的商户名是否像真实品牌名：不含连接词/动词，且非纯后缀。"""
    if len(name) < 3 or len(name) > 12:
        return False
    if GENERIC_PREFIXES.match(name):
        return False
    if name in ("门店", "店铺", "机构", "商户"):
        return False
    if any(ch in _CONNECTOR_CHARS for ch in name):
        return False
    return True

def extract_store(text: str) -> str:
    """提取涉事商户/门店名称。优先匹配引号内实体，再按句子切分匹配。"""
    suffix = r"(?:有限公司|信息技术有限公司|科技有限公司|公司|平台|APP|美容院|美容|美发店|理发店|健身房|健身|养生馆|洗浴中心|儿童乐园|早教|培训|瑜伽馆|舞蹈|游泳馆|口腔|医美|会所|门店|店铺|机构|商户)"
    brand = r"[一-鿿A-Za-z0-9·（）]{2,8}"

    def _search_in_segment(seg):
        q = re.findall(r"[「『“”](" + brand + suffix + r")[」』“”]", seg)
        if q:
            return max(q, key=len)
        m = re.findall(r"(" + brand + suffix + r")", seg)
        candidates = [x.strip(" 　,。；;:！") for x in m]
        lm = re.findall(r"(?:投诉对象|涉事门店|商家|店名|收款方|平台)[:：为是\s]*[「『“”]?([一-鿿A-Za-z0-9]{2,8})", seg)
        candidates.extend(x.strip(" 　,。；;:！") for x in lm)
        return candidates

    quoted = re.findall(r"[「『“”](" + brand + suffix + r")[」』“”]", text)
    if quoted:
        return max(quoted, key=len)

    sentences = _SENT_SPLIT.split(text)
    all_candidates = []
    for seg in sentences:
        result = _search_in_segment(seg)
        if isinstance(result, str):
            return result
        all_candidates.extend(result)

    valid = [n for n in all_candidates if _is_valid_store_name(n)]
    if valid:
        return max(valid, key=len)
    if all_candidates:
        return max(all_candidates, key=len)
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
