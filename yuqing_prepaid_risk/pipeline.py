from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from typing import Any, Dict, List, Sequence, Tuple

from .dedup import (
    apply_final_dedup,
    apply_llm_dedup,
    content_signature,
    event_key,
    is_cpu_dedup_reason,
    similarity_text,
)
from .io_utils import normalize_row
from .llm import apply_model_judgement, build_processed_item, should_use_llm
from .models import ProcessedItem
from .rules import build_summary, classify_risk
from .utils import log

def process_rows(
    rows: List[Dict[str, Any]],
    target_city: str,
    target_province: str,
    districts: Sequence[str],
    fuzzy_threshold: float,
    include_suspected: bool,
    args: argparse.Namespace,
) -> Tuple[List[ProcessedItem], Dict[str, int]]:
    exact_seen: Dict[str, int] = {}
    url_seen: Dict[str, int] = {}
    event_seen: Dict[str, int] = {}
    kept_texts: List[Tuple[str, int]] = []
    results: List[ProcessedItem] = []
    llm_tasks: List[Tuple[int, Dict[str, Any], Tuple[str, str, bool, str]]] = []

    for index, raw in enumerate(rows, 1):
        row = normalize_row(raw)
        row["id"] = index
        fallback = classify_risk(row, target_city, target_province, districts)
        risk_level, risk_label, keep, filter_reason = fallback
        summary = build_summary(row, risk_level, target_city, districts)
        model_used = "否"
        model_reason = ""
        if risk_level == "五级不实传言" and not include_suspected:
            keep = False
            filter_reason = "不实传言待人工复核"

        sig = content_signature(row)
        url = str(row.get("url") or "").strip()
        key = event_key(row)
        dedup_key = key
        dedup_reason = "保留"

        if not keep:
            results.append(
                build_processed_item(
                    row, risk_level, risk_label, False, filter_reason, summary, dedup_key, filter_reason, model_used, model_reason
                )
            )
            if should_use_llm(row, fallback, args):
                llm_tasks.append((len(results) - 1, row, fallback))
            continue

        if url and url in url_seen:
            results.append(
                build_processed_item(
                    row, risk_level, risk_label, False, "URL精准去重", summary, url, "URL精准去重", model_used, model_reason
                )
            )
            continue
        if sig in exact_seen:
            results.append(
                build_processed_item(
                    row, risk_level, risk_label, False, "全文精准去重", summary, sig, "全文精准去重", model_used, model_reason
                )
            )
            continue
        if key in event_seen:
            results.append(
                build_processed_item(
                    row, risk_level, risk_label, False, "同门店同事件归并", summary, key, "同门店同事件归并", model_used, model_reason
                )
            )
            continue

        text = similarity_text(row)
        fuzzy_duplicate = False
        for previous_text, previous_index in kept_texts:
            if not text or not previous_text:
                continue
            quick_ratio = SequenceMatcher(None, text[:300], previous_text[:300]).quick_ratio()
            if quick_ratio < fuzzy_threshold - 0.08:
                continue
            ratio = SequenceMatcher(None, text, previous_text).ratio()
            if ratio >= fuzzy_threshold:
                dedup_reason = f"相似文案模糊去重:#{previous_index}"
                fuzzy_duplicate = True
                break
        if fuzzy_duplicate:
            results.append(
                build_processed_item(
                    row, risk_level, risk_label, False, dedup_reason, summary, dedup_key, dedup_reason, model_used, model_reason
                )
            )
            continue

        if url:
            url_seen[url] = index
        exact_seen[sig] = index
        event_seen[key] = index
        kept_texts.append((text, index))
        results.append(build_processed_item(row, risk_level, risk_label, summary=summary, keep=True, filter_reason="", dedup_key=dedup_key, dedup_reason="保留", model_used=model_used, model_reason=model_reason))
        if should_use_llm(row, fallback, args):
            llm_tasks.append((len(results) - 1, row, fallback))

    if llm_tasks:
        log(f"大模型任务准备完成: mode={args.analysis_mode}, tasks={len(llm_tasks)}, workers={args.llm_workers}")
        with ThreadPoolExecutor(max_workers=max(1, args.llm_workers)) as executor:
            future_map = {
                executor.submit(apply_model_judgement, row, args, fallback, target_city, districts): result_index
                for result_index, row, fallback in llm_tasks
            }
            for future in as_completed(future_map):
                result_index = future_map[future]
                item = results[result_index]
                risk_level, risk_label, keep, filter_reason, summary, model_reason = future.result()
                if risk_level == "五级不实传言" and not include_suspected:
                    keep = False
                    filter_reason = "不实传言待人工复核"
                dedup_reason = "保留" if keep else (filter_reason or risk_label or risk_level)
                results[result_index] = build_processed_item(
                    item.row,
                    risk_level,
                    risk_label,
                    keep,
                    filter_reason,
                    summary,
                    item.dedup_key,
                    dedup_reason,
                    "是",
                    model_reason,
                )

    results = apply_final_dedup(results, fuzzy_threshold)
    results = apply_llm_dedup(results, args)

    stats = defaultdict(int)
    stats["输入总量"] = len(rows)
    stats["输出总量"] = 0
    stats["大模型调用量"] = sum(1 for item in results if item.model_used == "是")
    stats["最终保留条数"] = 0
    stats["CPU风险过滤条数"] = 0
    stats["CPU去重条数"] = 0
    for item in results:
        if item.keep:
            stats["输出总量"] += 1
            stats["保留高风险"] += 1
            stats["最终保留条数"] += 1
        else:
            reason = item.filter_reason or item.dedup_reason or "过滤"
            stats[reason] += 1
            if is_cpu_dedup_reason(reason):
                stats["CPU去重条数"] += 1
            else:
                stats["CPU风险过滤条数"] += 1

    return results, dict(stats)
