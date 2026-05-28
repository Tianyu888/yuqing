from __future__ import annotations

import argparse
import hashlib
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from typing import Any, Dict, List, Sequence, Tuple

from .config import EXTERNAL_CITY_WORDS
from .llm import build_processed_item, call_dedup_model, can_use_llm
from .models import ProcessedItem
from .rules import extract_amount, extract_category, extract_event, extract_location, extract_store
from .utils import compact_text, norm_text, log

CPU_DEDUP_REASONS = {"URL精准去重", "全文精准去重", "同门店同事件归并"}
FINAL_DEDUP_REASONS = {"最终URL精准去重", "最终全文精准去重", "最终同门店同事件归并"}
CANONICAL_SUBJECTS = [
    ("无锡荟聚fun服装店", ["无锡荟聚fun服装店", "荟聚fun服装店", "荟聚 fun服装店"]),
    ("海狸家口腔", ["海狸家口腔", "海狸家", "知名口腔机构"]),
    ("爱家月子中心", ["爱家月子中心", "江苏爱之家", "爱之家月子中心"]),
    ("爱容御美容美发", ["爱容御", "容御鑫美容美发", "爱容御保利店"]),
    ("中体星荟教培", ["中体星荟", "中体威博"]),
    ("无锡五八悦家", ["无锡五八悦家", "58旺铺", "58同城商家版", "五八悦家"]),
]


def is_cpu_dedup_reason(reason: str) -> bool:
    return (
        reason in CPU_DEDUP_REASONS
        or reason in FINAL_DEDUP_REASONS
        or reason.startswith("相似文案模糊去重")
        or reason.startswith("最终相似文案模糊去重")
        or reason.startswith("大模型同事件归并")
    )


def content_signature(row: Dict[str, Any]) -> str:
    text = norm_text((row.get("title") or "") + (row.get("content") or ""))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def canonical_subject(text: str) -> str:
    normalized = norm_text(text)
    for subject, aliases in CANONICAL_SUBJECTS:
        if any(norm_text(alias) in normalized for alias in aliases):
            return subject
    patterns = [
        r"涉事主体[为：:]\s*([^，；。;]+)",
        r"涉事商户[为：:]\s*([^，；。;]+)",
        r"投诉对象[为：:]\s*([^，；。;]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            subject = re.sub(r"[（(].*?[）)]", "", match.group(1)).strip()
            if 3 <= len(subject) <= 30:
                return subject
    return ""


def event_key(row: Dict[str, Any]) -> str:
    text = f"{row.get('title','')} {row.get('content','')}"
    subject = norm_text(canonical_subject(text))
    if subject:
        return f"subject:{subject}:{extract_event(text)}"
    store = norm_text(extract_store(text))
    loc = norm_text(extract_location(text, "", []))
    event = extract_event(text)
    amount = norm_text(extract_amount(text))
    if store and amount:
        return f"store:{store}:{event}:{amount}"
    if store:
        return f"store:{store}:{event}"
    title = norm_text(row.get("title", ""))[:40]
    return f"title:{loc}:{event}:{title}"


def similarity_text(row: Dict[str, Any]) -> str:
    text = norm_text((row.get("title") or "") + (row.get("content") or ""))
    return text[:1200]


def apply_final_dedup(results: List[ProcessedItem], fuzzy_threshold: float) -> List[ProcessedItem]:
    """Re-run dedup after model review so LLM-promoted rows cannot bypass it."""
    exact_seen: Dict[str, int] = {}
    url_seen: Dict[str, int] = {}
    event_seen: Dict[str, int] = {}
    kept_texts: List[Tuple[str, int]] = []
    final_results: List[ProcessedItem] = []

    for item in results:
        if not item.keep:
            final_results.append(item)
            continue

        row = item.row
        row_id = int(row.get("id") or len(final_results) + 1)
        sig = content_signature(row)
        url = str(row.get("url") or "").strip()
        key = event_key(row)
        dedup_key = item.dedup_key or key
        dedup_reason = ""

        if url and url in url_seen:
            dedup_key = url
            dedup_reason = "最终URL精准去重"
        elif sig in exact_seen:
            dedup_key = sig
            dedup_reason = "最终全文精准去重"
        elif key in event_seen:
            dedup_key = key
            dedup_reason = "最终同门店同事件归并"
        else:
            text = similarity_text(row)
            for previous_text, previous_index in kept_texts:
                if not text or not previous_text:
                    continue
                quick_ratio = SequenceMatcher(None, text[:300], previous_text[:300]).quick_ratio()
                if quick_ratio < fuzzy_threshold - 0.08:
                    continue
                ratio = SequenceMatcher(None, text, previous_text).ratio()
                if ratio >= fuzzy_threshold:
                    dedup_reason = f"最终相似文案模糊去重:#{previous_index}"
                    break

        if dedup_reason:
            final_results.append(
                build_processed_item(
                    row,
                    item.risk_level,
                    item.risk_label,
                    False,
                    dedup_reason,
                    item.risk_summary,
                    dedup_key,
                    dedup_reason,
                    item.model_used,
                    item.model_reason,
                )
            )
            continue

        if url:
            url_seen[url] = row_id
        exact_seen[sig] = row_id
        event_seen[key] = row_id
        kept_texts.append((similarity_text(row), row_id))
        final_results.append(
            build_processed_item(
                row,
                item.risk_level,
                item.risk_label,
                True,
                "",
                item.risk_summary,
                dedup_key,
                "保留",
                item.model_used,
                item.model_reason,
            )
        )

    return final_results


def dedup_candidate_keys(item: ProcessedItem) -> List[str]:
    row = item.row
    title_key = norm_text(row.get("title", ""))
    text = f"{row.get('title','')} {row.get('content','')} {item.risk_summary}"
    subject_key = norm_text(canonical_subject(text))
    store_key = norm_text(extract_store(text))
    entity_keys = extract_dedup_entities(text)
    topic_keys = extract_dedup_topics(text)
    keys = []
    if len(title_key) >= 8:
        keys.append(f"title:{title_key}")
    if len(subject_key) >= 4:
        keys.append(f"subject:{subject_key}")
    if len(store_key) >= 4:
        keys.append(f"store:{store_key}")
    for entity in entity_keys:
        keys.append(f"entity:{entity}")
    for topic in topic_keys:
        keys.append(f"topic:{topic}")
    return keys


def extract_dedup_entities(text: str) -> List[str]:
    entities = set()
    patterns = [
        r"[「『“\"]([\u4e00-\u9fffA-Za-z0-9·（）()]{2,40}(?:有限公司|信息技术有限公司|科技有限公司|公司|平台|APP|面包花园|面包店|烘焙|甜甜|饼店|点心局|Cooking Studio|医院|4S店|健身房|美容院|理发店|培训机构|瑜伽馆|门店|店铺|机构))[」』”\"]",
        r"([\u4e00-\u9fffA-Za-z0-9·（）()]{2,40}(?:有限公司|信息技术有限公司|科技有限公司|公司|平台|APP|面包花园|面包店|烘焙|甜甜|饼店|点心局|Cooking Studio|医院|4S店|健身房|美容院|理发店|培训机构|瑜伽馆|门店|店铺|机构))",
        r"(?:品牌|商户|门店|医院|机构|投诉对象|涉事主体|收款方|平台)[:：为是\s]*[「『“\"]?([\u4e00-\u9fffA-Za-z0-9·（）()]{2,40})",
    ]
    stop_words = {"天价面包", "网红烘焙", "高价套路", "昔日高利润赛道商户", "本土烘焙巨头"}
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            entity = norm_text(match.group(1))
            if len(entity) >= 4 and entity not in stop_words:
                entities.add(entity)
    return sorted(entities)


def extract_dedup_topics(text: str) -> List[str]:
    normalized = norm_text(text)
    topics = set()
    has_bakery = any(word in text for word in ["烘焙", "面包", "糕点", "甜品", "点心"])
    has_mass_closure = any(word in text for word in ["9万", "九万", "近九万", "上万", "万家", "倒闭潮", "退场", "批量失联"])
    has_loss_story = any(word in text for word in ["5个月", "五个月", "两百万", "200万", "高利润赛道", "暴利生意"])
    if has_bakery and (has_mass_closure or has_loss_story):
        topics.add("烘焙行业闭店潮预付卡风险")
    if "顶东面包花园" in text:
        topics.add("顶东面包花园闭店储值卡风险")
    if "多乐之日" in text:
        topics.add("多乐之日闭店储值卡风险")
    if "兰州仁和医院" in text:
        topics.add("兰州仁和医院医美消费争议")
    if "奥迪" in text and any(word in text for word in ["4S店", "保养套餐", "套餐"]):
        topics.add("奥迪4S店保养套餐闭店风险")
    if "中体星荟" in text or "中体威博" in text:
        topics.add("中体星荟教培课包退费风险")
    if any(word in text for word in ["58旺铺", "58同城商家版", "五八悦家", "无锡五八悦家"]):
        amount = extract_amount(text)
        amount_part = amount or "未知金额"
        topics.add(f"58旺铺会员服务退款投诉:{amount_part}")
    if normalized:
        for city in EXTERNAL_CITY_WORDS:
            if city in text and any(word in text for word in ["医院", "4S店", "培训", "健身", "美容", "理发", "烘焙", "面包"]):
                category = extract_category(text)
                event = extract_event(text)
                topics.add(norm_text(f"{city}{category}{event}"))
    return sorted(topics)


def append_model_reason(existing: str, addition: str) -> str:
    existing = compact_text(existing, 260)
    addition = compact_text(addition, 260)
    if existing and addition:
        return compact_text(f"{existing}；{addition}", 500)
    return existing or addition


def apply_llm_dedup(results: List[ProcessedItem], args: argparse.Namespace) -> List[ProcessedItem]:
    if not can_use_llm(args):
        return results

    groups: Dict[str, List[int]] = defaultdict(list)
    for index, item in enumerate(results):
        if not item.keep:
            continue
        for key in dedup_candidate_keys(item):
            groups[key].append(index)

    keeper_candidates: Dict[int, set[int]] = defaultdict(set)
    for indices in groups.values():
        unique_indices = sorted(set(indices))
        if len(unique_indices) < 2:
            continue
        keeper_index = unique_indices[0]
        keeper_candidates[keeper_index].update(unique_indices[1:])

    candidate_groups: List[List[int]] = []
    for keeper_index in sorted(keeper_candidates):
        candidates = sorted(keeper_candidates[keeper_index])
        for start in range(0, len(candidates), 7):
            candidate_groups.append([keeper_index, *candidates[start : start + 7]])

    if not candidate_groups:
        return results

    workers = max(1, int(getattr(args, "llm_workers", 1) or 1))
    log(f"大模型辅助去重任务准备完成: groups={len(candidate_groups)}, workers={workers}")
    final_results = list(results)
    removed_ids = set()

    def review_group(group_indices: List[int]) -> Tuple[List[int], Dict[str, Any] | None, str]:
        group_items = [results[i] for i in group_indices]
        keeper_id = str(group_items[0].row.get("id", ""))
        try:
            return group_indices, call_dedup_model(group_items, args), ""
        except Exception as exc:
            return group_indices, None, str(exc)

    reviewed_groups: List[Tuple[List[int], Dict[str, Any] | None, str]] = []
    if workers == 1 or len(candidate_groups) == 1:
        reviewed_groups = [review_group(group_indices) for group_indices in candidate_groups]
    else:
        group_order = {id(group_indices): order for order, group_indices in enumerate(candidate_groups)}
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {executor.submit(review_group, group_indices): group_indices for group_indices in candidate_groups}
            for future in as_completed(future_map):
                reviewed_groups.append(future.result())
        reviewed_groups.sort(key=lambda x: group_order.get(id(x[0]), 0))

    for group_indices, model_result, error in reviewed_groups:
        live_indices = [i for i in group_indices if final_results[i].keep and str(final_results[i].row.get("id", "")) not in removed_ids]
        if len(live_indices) < 2:
            continue
        keeper = final_results[live_indices[0]]
        keeper_id = str(keeper.row.get("id", ""))
        if error or not model_result:
            log(f"大模型辅助去重失败: keeper_id={keeper_id}, error={error}")
            continue

        duplicate_ids = set(model_result.get("duplicate_ids") or set())
        duplicate_ids.discard(keeper_id)
        reason = compact_text(model_result.get("reason"), 260) or "模型判断为同一事件/同一门店重复舆情"
        if not duplicate_ids:
            continue

        log(f"大模型辅助去重完成: keeper_id={keeper_id}, duplicates={sorted(duplicate_ids)}")
        for index in live_indices[1:]:
            item = final_results[index]
            row_id = str(item.row.get("id", ""))
            if row_id not in duplicate_ids:
                continue
            removed_ids.add(row_id)
            dedup_reason = f"大模型同事件归并:#{keeper_id}"
            final_results[index] = build_processed_item(
                item.row,
                item.risk_level,
                item.risk_label,
                False,
                dedup_reason,
                item.risk_summary,
                f"llm_dedup:{keeper_id}",
                dedup_reason,
                "是",
                append_model_reason(item.model_reason, f"大模型辅助去重：{reason}"),
            )

    return final_results
