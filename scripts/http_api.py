#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import traceback
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from yuqing_prepaid_risk.service import (  # noqa: E402
    LlmApiTestOptions,
    RawExportOptions,
    RiskAnalysisOptions,
    YuqingApiTestOptions,
    export_raw_yuqing,
    run_risk_analysis,
    test_llm_api,
    test_yuqing_api,
)

JOBS: Dict[str, Dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()
SERVER_TOKEN = ""

CAMEL_TO_SNAKE = {
    "appKey": "app_key",
    "secureKey": "secure_key",
    "themeName": "theme_name",
    "newsType": "news_type",
    "dateType": "date_type",
    "beginDate": "begin_date",
    "endDate": "end_date",
    "pageCount": "page_count",
    "maxPages": "max_pages",
    "payloadFormat": "payload_format",
    "modelUrl": "model_url",
    "modelKey": "model_key",
    "modelName": "model_name",
    "llmApiUrl": "llm_api_url",
    "llmApiKey": "llm_api_key",
    "llmModel": "llm_model",
    "llmTimeout": "llm_timeout",
    "llmContentChars": "llm_content_chars",
    "analysisMode": "analysis_mode",
    "llmWorkers": "llm_workers",
    "disableLlm": "disable_llm",
    "targetCity": "target_city",
    "targetProvince": "target_province",
    "fuzzyThreshold": "fuzzy_threshold",
    "includeFiltered": "include_filtered",
    "includeSuspected": "include_suspected",
}


def normalize_options(data: Dict[str, Any]) -> Dict[str, Any]:
    options = data.get("options") if isinstance(data.get("options"), dict) else data
    ignored = {"write_output", "include_items", "include_rows", "async", "options"}
    normalized: Dict[str, Any] = {}
    for key, value in options.items():
        if key in ignored:
            continue
        normalized[CAMEL_TO_SNAKE.get(key, key)] = value
    return normalized


def json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [json_safe(v) for v in value]
    return value


def json_response(handler: BaseHTTPRequestHandler, data: Dict[str, Any], status: int = 200) -> None:
    body = json.dumps(json_safe(data), ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json_body(handler: BaseHTTPRequestHandler) -> Dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        return {}
    raw = handler.rfile.read(length).decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("请求体必须是 JSON object")
    return data


def check_auth(handler: BaseHTTPRequestHandler) -> bool:
    if not SERVER_TOKEN:
        return True
    expected = f"Bearer {SERVER_TOKEN}"
    return handler.headers.get("Authorization", "") == expected


def route_info(host: str, port: int) -> Dict[str, Any]:
    base = f"http://{host}:{port}"
    return {
        "ok": True,
        "routes": {
            "GET /health": f"{base}/health",
            "GET /api/routes": f"{base}/api/routes",
            "POST /api/risk-analysis": "同步运行风险筛选",
            "POST /api/raw-export": "同步导出舆情 API 原始结果",
            "POST /api/test-yuqing": "测试舆情 API 连通性",
            "POST /api/test-llm": "测试大模型 API 连通性",
            "POST /api/jobs/risk-analysis": "异步运行风险筛选，返回 job_id",
            "POST /api/jobs/raw-export": "异步导出原始结果，返回 job_id",
            "GET /api/jobs/{job_id}": "查询异步任务状态和结果",
        },
        "request_body": {
            "options": "可选。放脚本参数，支持 snake_case 和常见 camelCase，例如 date_type/dateType。",
            "write_output": "可选。是否写 Excel，默认 true。",
            "include_items": "风险筛选可选。是否返回明细，默认 false。",
            "include_rows": "原始导出可选。是否返回原始行，默认 false。",
        },
    }


def call_risk(data: Dict[str, Any]) -> Dict[str, Any]:
    include_items = bool(data.get("include_items", False))
    write_output = bool(data.get("write_output", True))
    result = run_risk_analysis(
        RiskAnalysisOptions(**normalize_options(data)),
        write_output=write_output,
        include_items=include_items,
    )
    return {"ok": True, "result": result}


def call_raw(data: Dict[str, Any]) -> Dict[str, Any]:
    include_rows = bool(data.get("include_rows", False))
    write_output = bool(data.get("write_output", True))
    result = export_raw_yuqing(RawExportOptions(**normalize_options(data)), write_output=write_output)
    if not include_rows:
        result.pop("rows", None)
    return {"ok": True, "result": result}


def call_yuqing_test(data: Dict[str, Any]) -> Dict[str, Any]:
    result = test_yuqing_api(YuqingApiTestOptions(**normalize_options(data)))
    return {"ok": True, "result": result}


def call_llm_test(data: Dict[str, Any]) -> Dict[str, Any]:
    result = test_llm_api(LlmApiTestOptions(**normalize_options(data)))
    return {"ok": True, "result": result}


def create_job(kind: str, func: Callable[[Dict[str, Any]], Dict[str, Any]], data: Dict[str, Any]) -> Dict[str, Any]:
    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "kind": kind,
            "status": "queued",
            "created_at": time.time(),
            "started_at": None,
            "finished_at": None,
            "result": None,
            "error": "",
        }
    thread = threading.Thread(target=run_job, args=(job_id, func, data), daemon=True)
    thread.start()
    return {"ok": True, "job_id": job_id, "status_url": f"/api/jobs/{job_id}"}


def run_job(job_id: str, func: Callable[[Dict[str, Any]], Dict[str, Any]], data: Dict[str, Any]) -> None:
    with JOBS_LOCK:
        JOBS[job_id]["status"] = "running"
        JOBS[job_id]["started_at"] = time.time()
    try:
        result = func(data)
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "finished"
            JOBS[job_id]["finished_at"] = time.time()
            JOBS[job_id]["result"] = result
    except Exception as exc:
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "failed"
            JOBS[job_id]["finished_at"] = time.time()
            JOBS[job_id]["error"] = str(exc)
            JOBS[job_id]["traceback"] = traceback.format_exc(limit=6)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def do_GET(self) -> None:
        if not check_auth(self):
            json_response(self, {"ok": False, "error": "unauthorized"}, 401)
            return
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            json_response(self, {"ok": True, "status": "healthy"})
            return
        if parsed.path == "/api/routes":
            host, port = self.server.server_address[:2]
            json_response(self, route_info(str(host), int(port)))
            return
        if parsed.path.startswith("/api/jobs/"):
            job_id = parsed.path.rsplit("/", 1)[-1]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                if not job:
                    json_response(self, {"ok": False, "error": "job not found"}, 404)
                    return
                json_response(self, {"ok": True, "job": job})
            return
        json_response(self, {"ok": False, "error": "not found"}, 404)

    def do_POST(self) -> None:
        if not check_auth(self):
            json_response(self, {"ok": False, "error": "unauthorized"}, 401)
            return
        parsed = urlparse(self.path)
        try:
            data = read_json_body(self)
            if parsed.path == "/api/risk-analysis":
                json_response(self, call_risk(data))
                return
            if parsed.path == "/api/raw-export":
                json_response(self, call_raw(data))
                return
            if parsed.path == "/api/test-yuqing":
                json_response(self, call_yuqing_test(data))
                return
            if parsed.path == "/api/test-llm":
                json_response(self, call_llm_test(data))
                return
            if parsed.path == "/api/jobs/risk-analysis":
                json_response(self, create_job("risk-analysis", call_risk, data), 202)
                return
            if parsed.path == "/api/jobs/raw-export":
                json_response(self, create_job("raw-export", call_raw, data), 202)
                return
        except TypeError as exc:
            json_response(self, {"ok": False, "error": f"参数错误: {exc}"}, 400)
            return
        except Exception as exc:
            json_response(self, {"ok": False, "error": str(exc)}, 500)
            return
        json_response(self, {"ok": False, "error": "not found"}, 404)


def main() -> int:
    global SERVER_TOKEN
    parser = argparse.ArgumentParser(description="苏移舆情预充值风险 HTTP API 服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--token", default="", help="可选 Bearer Token；设置后请求需带 Authorization: Bearer <token>")
    args = parser.parse_args()
    SERVER_TOKEN = args.token
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"HTTP API 已启动: http://{args.host}:{args.port}")
    print("路由说明: GET /api/routes")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("HTTP API 已停止")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
