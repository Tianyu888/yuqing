from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any, Dict, List, Optional

import requests

from .config import THEME_API_URL
from .utils import log

def sign_authorization(app_key: str, secure_key: str, request_time: Optional[int] = None) -> str:
    request_time = request_time or int(time.time())
    request_time_text = str(request_time)
    date_signature = hmac.new(
        secure_key.encode("utf-8"),
        request_time_text.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    signature = hmac.new(
        date_signature.encode("utf-8"),
        app_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{app_key}/{request_time_text}/{signature}"


def post_api(
    url: str,
    params: Dict[str, Any],
    app_key: str,
    secure_key: str,
    timeout: int,
    payload_format: str,
) -> Dict[str, Any]:
    headers = {"authorization": sign_authorization(app_key, secure_key)}
    if payload_format == "json":
        headers["Content-Type"] = "application/json;charset=utf-8"
        response = requests.post(url, headers=headers, json=params, timeout=timeout)
    else:
        headers["Content-Type"] = "application/x-www-form-urlencoded;charset=utf-8"
        response = requests.post(url, headers=headers, data=params, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != 1:
        raise RuntimeError(f"API 返回失败: {payload.get('status_info')}")
    return payload


def fetch_yuqing(args: argparse.Namespace) -> List[Dict[str, Any]]:
    if not args.app_key or not args.secure_key:
        raise ValueError("调用 API 需要提供 --app-key 和 --secure-key，或设置 SUYIYU_APP_KEY/SUYIYU_SECURE_KEY")

    base_params = {
        "theme_name": args.theme_name,
        "news_type": args.news_type,
        "attribute": args.attribute,
        "date_type": args.date_type,
    }
    if args.date_type == 0:
        base_params["begin_date"] = args.begin_date
        base_params["end_date"] = args.end_date
    rows = fetch_pages(THEME_API_URL, base_params, args)
    log(f"舆情接口获取完成: theme={args.theme_name}, rows={len(rows)}")
    return rows


def fetch_pages(url: str, base_params: Dict[str, Any], args: argparse.Namespace) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    max_pages = args.max_pages
    for page in range(1, max_pages + 1):
        params = dict(base_params)
        params["page"] = page
        params["page_count"] = args.page_count
        payload = post_api(url, params, args.app_key, args.secure_key, args.timeout, args.payload_format)
        data = payload.get("data") or {}
        data_list = data.get("data_list") or []
        for item in data_list:
            rows.append(normalize_row(item))
        total_num = int(data.get("total_num") or 0)
        if not data_list or len(rows) >= total_num:
            break
        time.sleep(args.sleep)
    return rows
