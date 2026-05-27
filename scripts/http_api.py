#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

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

app = FastAPI(
    title="苏移舆情预充值风险 HTTP API",
    version="1.0.0",
    description="通过 HTTP 调用舆情风险筛选、原始导出、舆情 API 连通性测试和大模型连通性测试。",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ApiRequest(BaseModel):
    options: Dict[str, Any] = Field(default_factory=dict, description="脚本参数，支持 snake_case 和常见 camelCase")
    write_output: bool = Field(True, description="是否写 Excel")
    include_items: bool = Field(False, description="风险筛选是否返回明细")
    include_rows: bool = Field(False, description="原始导出是否返回原始行")


def normalize_options(data: Dict[str, Any]) -> Dict[str, Any]:
    options = data.get("options") if isinstance(data.get("options"), dict) else data
    ignored = {"write_output", "include_items", "include_rows", "async", "options"}
    normalized: Dict[str, Any] = {}
    for key, value in options.items():
        if key in ignored:
            continue
        normalized[CAMEL_TO_SNAKE.get(key, key)] = value
    return normalized


def normalize_risk_options(data: Dict[str, Any]) -> Dict[str, Any]:
    normalized = normalize_options(data)
    aliases = {
        "model_url": "llm_api_url",
        "model_key": "llm_api_key",
        "model_name": "llm_model",
    }
    for source, target in aliases.items():
        if source in normalized and target not in normalized:
            normalized[target] = normalized.pop(source)
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


def request_to_dict(payload: Optional[ApiRequest]) -> Dict[str, Any]:
    if payload is None:
        return {}
    return payload.dict()


async def optional_body(request: Request) -> ApiRequest:
    raw = await request.body()
    if not raw:
        return ApiRequest()
    return ApiRequest.parse_raw(raw)


def verify_auth(authorization: str = Header(default="")) -> None:
    if not SERVER_TOKEN:
        return
    if authorization != f"Bearer {SERVER_TOKEN}":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")


def route_info(request: Request) -> Dict[str, Any]:
    base = str(request.base_url).rstrip("/")
    return {
        "ok": True,
        "docs": f"{base}/docs",
        "openapi": f"{base}/openapi.json",
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
    result = run_risk_analysis(
        RiskAnalysisOptions(**normalize_risk_options(data)),
        write_output=bool(data.get("write_output", True)),
        include_items=bool(data.get("include_items", False)),
    )
    return {"ok": True, "result": result}


def call_raw(data: Dict[str, Any]) -> Dict[str, Any]:
    result = export_raw_yuqing(
        RawExportOptions(**normalize_options(data)),
        write_output=bool(data.get("write_output", True)),
    )
    if not data.get("include_rows", False):
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


@app.exception_handler(Exception)
async def exception_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})


@app.exception_handler(ValueError)
async def value_error_handler(_: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})


@app.get("/health", dependencies=[Depends(verify_auth)])
def health() -> Dict[str, Any]:
    return {"ok": True, "status": "healthy"}


@app.get("/api/routes", dependencies=[Depends(verify_auth)])
def routes(request: Request) -> Dict[str, Any]:
    return route_info(request)


@app.post("/api/risk-analysis", dependencies=[Depends(verify_auth)])
def risk_analysis(payload: ApiRequest) -> Dict[str, Any]:
    return json_safe(call_risk(request_to_dict(payload)))


@app.post("/api/raw-export", dependencies=[Depends(verify_auth)])
def raw_export(payload: ApiRequest) -> Dict[str, Any]:
    return json_safe(call_raw(request_to_dict(payload)))


@app.post("/api/test-yuqing", dependencies=[Depends(verify_auth)])
def yuqing_api_test(payload: ApiRequest = Depends(optional_body)) -> Dict[str, Any]:
    return json_safe(call_yuqing_test(request_to_dict(payload)))


@app.post("/api/test-llm", dependencies=[Depends(verify_auth)])
def llm_api_test(payload: ApiRequest = Depends(optional_body)) -> Dict[str, Any]:
    return json_safe(call_llm_test(request_to_dict(payload)))


@app.post("/api/jobs/risk-analysis", status_code=202, dependencies=[Depends(verify_auth)])
def create_risk_job(payload: ApiRequest, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    data = request_to_dict(payload)
    response = create_job("risk-analysis", call_risk, data)
    background_tasks.add_task(run_job, response["job_id"], call_risk, data)
    return response


@app.post("/api/jobs/raw-export", status_code=202, dependencies=[Depends(verify_auth)])
def create_raw_job(payload: ApiRequest, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    data = request_to_dict(payload)
    response = create_job("raw-export", call_raw, data)
    background_tasks.add_task(run_job, response["job_id"], call_raw, data)
    return response


@app.get("/api/jobs/{job_id}", dependencies=[Depends(verify_auth)])
def get_job(job_id: str) -> Dict[str, Any]:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return {"ok": True, "job": json_safe(job)}


def main() -> int:
    global SERVER_TOKEN
    parser = argparse.ArgumentParser(description="苏移舆情预充值风险 HTTP API 服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--token", default="", help="可选 Bearer Token；设置后请求需带 Authorization: Bearer <token>")
    args = parser.parse_args()
    SERVER_TOKEN = args.token

    import uvicorn

    print(f"HTTP API 已启动: http://{args.host}:{args.port}")
    print(f"Swagger 文档: http://{args.host}:{args.port}/docs")
    print("路由说明: GET /api/routes")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
