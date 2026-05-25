from __future__ import annotations

import argparse
import json
import re
from typing import Any, Dict, Optional, Sequence, Tuple

import requests

from .config import BUSINESS_WORDS, EXPIRED_WORDS, PREPAID_WORDS, RUMOR_WORDS, RUNAWAY_WORDS
from .models import ProcessedItem
from .rules import build_summary
from .utils import compact_text, contains_any, log

def extract_json_object(text: str) -> Dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.I | re.M).strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.S)
    if not match:
        raise ValueError(f"模型未返回 JSON: {text[:200]}")
    return json.loads(match.group(0))


def call_risk_model(row: Dict[str, Any], args: argparse.Namespace) -> Optional[Dict[str, Any]]:
    if args.disable_llm or not args.llm_api_key or not args.llm_api_url or not args.llm_model:
        return None

    content = compact_text(row.get("content"), args.llm_content_chars)
    prompt = f"""
你是城运中心预充值卡商户跑路风险预警审核员。请只根据输入舆情判断是否属于预充值消费领域的商户跑路/闭店/失联/拒不退款风险。

判定等级只能使用以下五类之一：
1. 一级真实高风险负面：明确提及门店/商户 + 预充值/办卡/会员卡/课包/储值 + 关门停业/失联/跑路/拒不退款等事实，建议重点预警。
2. 二级普通消费：只有服务差、态度差、预约难、效果差、价格争议等普通消费纠纷，无闭店跑路事实。
3. 三级无效水帖 / 吐槽：无具体门店事实、广告软文、泛泛避坑、无关行业信息。
4. 四级过期旧闻：往年旧事、已退款、已处置、已完结。
5. 五级不实传言：只有猜测、传言、疑似跑路但无实锤，需要人工复核。

请返回严格 JSON，不要输出 Markdown：
{{
  "risk_level": "一级真实高风险负面/二级普通消费/三级无效水帖 / 吐槽/四级过期旧闻/五级不实传言",
  "risk_label": "重点预警，推送排查/直接过滤剔除/时效过滤剔除/标记存疑，人工复核",
  "keep": true 或 false,
  "risk_summary": "短句摘要，包含涉事主体、行业、地点、事件、群众诉求、来源和发布时间；无关信息也简述过滤原因",
  "reason": "一句话说明判定依据"
}}

舆情数据：
标题：{row.get("title", "")}
发布时间：{row.get("pubtime", "")}
来源：{row.get("source", "") or row.get("type", "")}
IP归属地：{row.get("iplocation", "")}
链接：{row.get("url", "")}
正文：{content}
""".strip()

    payload = {
        "model": args.llm_model,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "Authorization": f"Bearer {args.llm_api_key}",
        "Content-Type": "application/json",
    }
    response = requests.post(args.llm_api_url, json=payload, headers=headers, timeout=args.llm_timeout)
    response.raise_for_status()
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    result = extract_json_object(content)
    if not isinstance(result.get("keep"), bool):
        result["keep"] = str(result.get("keep", "")).lower() in {"true", "1", "yes", "是"}
    return result


def can_use_llm(args: argparse.Namespace) -> bool:
    return bool(
        not args.disable_llm
        and args.llm_api_key
        and args.llm_api_url
        and args.llm_model
        and args.analysis_mode != "cpu"
    )


def call_dedup_model(items: Sequence[ProcessedItem], args: argparse.Namespace) -> Dict[str, Any]:
    records = []
    for item in items:
        row = item.row
        content = compact_text(row.get("content"), min(args.llm_content_chars, 1800))
        records.append(
            {
                "id": row.get("id", ""),
                "title": compact_text(row.get("title"), 160),
                "pubtime": row.get("pubtime", ""),
                "source": row.get("source") or row.get("type") or "",
                "iplocation": row.get("iplocation", ""),
                "url": row.get("url", ""),
                "risk_summary": compact_text(item.risk_summary, 280),
                "content": content,
            }
        )

    prompt = f"""
你是城运中心预充值卡风险舆情去重审核员。请判断这些记录中，除第一条以外，哪些应并入第一条。

判断步骤：
1. 先从每条记录提取核心信息：主体/品牌/门店、地点、行业、预付费问题、闭店/失联/拒不退款事实、时间线。
2. 再判断是否描述同一风险事件或同一行业综述事件。
3. 输出时只给出应并入第一条的记录 id。

归并标准：
1. 同一事件不同转述：同一商户/品牌/门店或同一行业综述事件，核心事实相同，只是标题、开头、写法、来源不同。
2. 同一门店多用户投诉：同一门店/机构的预充值、闭店、失联、拒不退款事件，多个用户投诉也合并。
3. 相似话术投诉：主体、诉求、时间和风险事实高度相似，只保留一条。
4. 同一行业综述反复转述同一批案例和同一组数字，例如烘焙行业“近/超/9万家门店倒闭、5个月亏损200万、预付卡退款难、商户批量失联”，即使标题不同也归并。

不要归并：
1. 不同城市的不同门店、不同商户、不同时间独立爆雷事件。
2. 同一行业但具体主体和事实明显不同的风险事件。

请返回严格 JSON，不要输出 Markdown：
{{
  "duplicate_ids": [除第一条外应归并的记录id],
  "reason": "一句话说明归并依据"
}}

候选记录：
{json.dumps(records, ensure_ascii=False, indent=2)}
""".strip()

    payload = {
        "model": args.llm_model,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "Authorization": f"Bearer {args.llm_api_key}",
        "Content-Type": "application/json",
    }
    response = requests.post(args.llm_api_url, json=payload, headers=headers, timeout=args.llm_timeout)
    response.raise_for_status()
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    result = extract_json_object(content)
    duplicate_ids = result.get("duplicate_ids") or []
    if not isinstance(duplicate_ids, list):
        duplicate_ids = []
    result["duplicate_ids"] = {str(x) for x in duplicate_ids}
    result["reason"] = compact_text(result.get("reason"), 300)
    return result


def should_use_llm(
    row: Dict[str, Any],
    fallback: Tuple[str, str, bool, str],
    args: argparse.Namespace,
) -> bool:
    if args.disable_llm or not args.llm_api_key or not args.llm_api_url or not args.llm_model or args.analysis_mode == "cpu":
        return False

    risk_level, _, keep, filter_reason = fallback
    text = f"{row.get('title','')} {row.get('content','')}"
    has_prepaid = contains_any(text, PREPAID_WORDS)
    has_runaway = contains_any(text, RUNAWAY_WORDS)
    has_business = contains_any(text, BUSINESS_WORDS)
    has_rumor = contains_any(text, RUMOR_WORDS)
    has_expired = contains_any(text, EXPIRED_WORDS)

    # gpu 模式：CPU 规则优先，只把可能影响预警清单质量的记录交给模型复核。
    if keep:
        return True
    if risk_level in {"一级真实高风险负面", "五级不实传言"}:
        return True
    if filter_reason in {"地域过滤去重", "URL精准去重", "全文精准去重", "同门店同事件归并", "相似文案模糊去重"}:
        return False
    if has_prepaid and has_runaway:
        return True
    if has_runaway and has_business and (has_rumor or has_expired):
        return True
    return False


def apply_model_judgement(
    row: Dict[str, Any],
    args: argparse.Namespace,
    fallback: Tuple[str, str, bool, str],
    target_city: str,
    districts: Sequence[str],
) -> Tuple[str, str, bool, str, str, str]:
    risk_level, risk_label, keep, filter_reason = fallback
    try:
        log(f"调用大模型: id={row.get('id', '')}, title={compact_text(row.get('title'), 60)}")
        model_result = call_risk_model(row, args)
    except Exception as exc:
        summary = build_summary(row, risk_level, target_city, districts)
        log(f"大模型返回失败: id={row.get('id', '')}, error={exc}")
        return risk_level, risk_label, keep, filter_reason, summary, f"模型调用失败，使用规则结果: {exc}"

    if not model_result:
        summary = build_summary(row, risk_level, target_city, districts)
        return risk_level, risk_label, keep, filter_reason, summary, ""

    risk_level = str(model_result.get("risk_level") or risk_level)
    risk_label = str(model_result.get("risk_label") or risk_label)
    keep = bool(model_result.get("keep"))
    summary = compact_text(model_result.get("risk_summary") or build_summary(row, risk_level, target_city, districts), 500)
    reason = compact_text(model_result.get("reason"), 300)
    if not keep:
        filter_reason = risk_label or risk_level
    log(f"大模型返回完成: id={row.get('id', '')}, risk_level={risk_level}, keep={keep}")
    return risk_level, risk_label, keep, filter_reason, summary, reason


def build_processed_item(
    row: Dict[str, Any],
    risk_level: str,
    risk_label: str,
    keep: bool,
    filter_reason: str,
    summary: str,
    dedup_key: str,
    dedup_reason: str,
    model_used: str,
    model_reason: str,
) -> ProcessedItem:
    return ProcessedItem(
        row,
        risk_level,
        risk_label,
        summary,
        dedup_key,
        dedup_reason,
        keep,
        "" if keep else filter_reason,
        model_used,
        model_reason,
    )
