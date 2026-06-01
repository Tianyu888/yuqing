#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
JOBS: Dict[str, Dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()


PARAM_HELP: Dict[str, str] = {
    "task": "选择运行风险筛选流程，或直接导出舆情 API 原始数据。",
    "analysisMode": "风险筛选模式。cpu 只使用本地规则；gpu 会在规则初筛后调用 OpenAI-compatible 大模型复核和辅助去重。",
    "dateType": "舆情 API 时间范围。30 表示近 30 天；0 表示使用自定义开始和结束日期。",
    "beginDate": "当时间范围选择自定义时生效，格式建议为 YYYY-MM-DD。",
    "endDate": "当时间范围选择自定义时生效，格式建议为 YYYY-MM-DD。",
    "themeName": "苏移舆情专题名称，默认是风险研判。",
    "attribute": "情感类型。风险筛选通常使用 negative。",
    "newsType": "来源类型，默认 all。",
    "output": "Excel 输出路径。可以填相对路径，例如 outputs\\结果.xlsx。",
    "includeFiltered": "风险筛选时同时输出被过滤、去重的记录，方便审计规则效果。",
    "excludeSuspected": "风险筛选时不输出五级不实传言/存疑线索。",
    "pageCount": "接口单页数量。当前舆情 API 上限为 20，设置过大接口会报错。",
    "maxPages": "最多翻页页数。用于限制本次最多拉取多少页。",
    "sleep": "翻页请求间隔秒数，避免连续请求太快。",
    "payloadFormat": "接口请求体格式。默认 json；如果网关要求表单再改为 form。",
    "llmWorkers": "gpu 模式下大模型并发线程数。数值越高越快，但也更容易触发模型网关限流。",
    "llmTimeout": "大模型单次请求超时时间，单位秒。",
    "llmContentChars": "送入大模型的正文最大字符数。",
    "disableLlm": "强制关闭大模型，即使选择 gpu 模式也只按本地规则执行。",
    "modelUrl": "OpenAI-compatible 模型网关地址，例如 https://网关/v1；脚本会自动补齐 /chat/completions。",
    "modelKey": "大模型 API Key。留空则使用 .env 中的 LLM_API_KEY。",
    "modelName": "模型名称。留空则使用 .env 中的 LLM_MODEL。",
    "targetCity": "风险筛选目标城市，默认无锡市。",
    "targetProvince": "风险筛选目标省份，默认江苏省。",
    "districts": "辖区关键词，逗号分隔。",
    "fuzzyThreshold": "模糊去重相似度阈值，默认 0.90。越高越严格。",
}


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>苏移舆情预充值风险控制台</title>
  <style>
    :root {
      --bg: #f6f7f9;
      --panel: #ffffff;
      --line: #d9dee7;
      --text: #1f2937;
      --muted: #667085;
      --brand: #0f766e;
      --brand-dark: #115e59;
      --warn: #b45309;
      --danger: #b91c1c;
      --mono: Consolas, "SFMono-Regular", Menlo, monospace;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
    }
    header {
      height: 56px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 20px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    h1 { margin: 0; font-size: 18px; font-weight: 650; }
    main {
      display: grid;
      grid-template-columns: minmax(360px, 520px) 1fr;
      gap: 16px;
      padding: 16px;
      min-height: calc(100vh - 56px);
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
      min-width: 0;
    }
    .form-panel { overflow: auto; max-height: calc(100vh - 88px); }
    .panel-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
    }
    .panel-head h2 { margin: 0; font-size: 15px; }
    .panel-body { padding: 14px; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    .full { grid-column: 1 / -1; }
    label { display: block; color: #344054; font-size: 12px; margin-bottom: 5px; }
    input, select {
      width: 100%;
      height: 34px;
      border: 1px solid #cfd6e2;
      border-radius: 4px;
      padding: 6px 9px;
      background: #fff;
      color: var(--text);
      outline: none;
    }
    input:focus, select:focus { border-color: var(--brand); box-shadow: 0 0 0 2px rgba(15,118,110,.12); }
    input[type="checkbox"] { width: 16px; height: 16px; }
    .check-row { display: flex; align-items: center; gap: 8px; min-height: 34px; }
    .check-row label { margin: 0; font-size: 13px; }
    .help {
      min-height: 52px;
      padding: 10px 12px;
      background: #f8fafc;
      border: 1px solid var(--line);
      border-radius: 4px;
      color: var(--muted);
      margin-bottom: 12px;
    }
    .actions { display: flex; gap: 10px; align-items: center; margin-top: 14px; }
    button {
      height: 34px;
      border: 1px solid var(--brand);
      border-radius: 4px;
      padding: 0 13px;
      background: var(--brand);
      color: #fff;
      cursor: pointer;
      font-weight: 600;
    }
    button.secondary { color: var(--brand-dark); background: #fff; }
    button:disabled { opacity: .55; cursor: not-allowed; }
    .status { color: var(--muted); }
    .log {
      height: calc(100vh - 175px);
      overflow: auto;
      margin: 0;
      padding: 12px;
      background: #101828;
      color: #d1fadf;
      font: 13px/1.55 var(--mono);
      white-space: pre-wrap;
      border-radius: 0 0 6px 6px;
    }
    .file-row {
      display: flex;
      align-items: center;
      gap: 10px;
      color: var(--muted);
      font-size: 13px;
    }
    .file-row a { color: var(--brand-dark); text-decoration: none; font-weight: 600; }
    @media (max-width: 920px) {
      main { grid-template-columns: 1fr; }
      .form-panel { max-height: none; }
      .log { height: 420px; }
    }
  </style>
</head>
<body>
  <header>
    <h1>苏移舆情预充值风险控制台</h1>
    <span class="status" id="envStatus">读取配置中</span>
  </header>
  <main>
    <section class="form-panel">
      <div class="panel-head"><h2>运行参数</h2><span class="status" id="jobStatus">未运行</span></div>
      <div class="panel-body">
        <div class="help" id="paramHelp">点击或聚焦任意参数查看含义。</div>
        <form id="runForm">
          <div class="grid">
            <div class="full">
              <label for="task">任务</label>
              <select id="task" name="task" data-help="task">
                <option value="risk">风险筛选输出</option>
                <option value="raw">原始舆情导出</option>
              </select>
            </div>
            <div>
              <label for="analysisMode">研判模式</label>
              <select id="analysisMode" name="analysisMode" data-help="analysisMode">
                <option value="gpu">gpu</option>
                <option value="cpu">cpu</option>
              </select>
            </div>
            <div>
              <label for="dateType">时间范围</label>
              <select id="dateType" name="dateType" data-help="dateType">
                <option value="30">近 30 天</option>
                <option value="7">近 7 天</option>
                <option value="1">近 1 天</option>
                <option value="0">自定义日期</option>
              </select>
            </div>
            <div>
              <label for="beginDate">开始日期</label>
              <input id="beginDate" name="beginDate" data-help="beginDate" placeholder="2026-05-01">
            </div>
            <div>
              <label for="endDate">结束日期</label>
              <input id="endDate" name="endDate" data-help="endDate" placeholder="2026-05-25">
            </div>
            <div>
              <label for="themeName">专题名称</label>
              <input id="themeName" name="themeName" data-help="themeName" value="风险研判">
            </div>
            <div>
              <label for="attribute">情感类型</label>
              <select id="attribute" name="attribute" data-help="attribute">
                <option value="negative">negative</option>
                <option value="all">all</option>
                <option value="neutral">neutral</option>
                <option value="positive">positive</option>
              </select>
            </div>
            <div>
              <label for="newsType">来源类型</label>
              <input id="newsType" name="newsType" data-help="newsType" value="all">
            </div>
            <div>
              <label for="output">输出 Excel</label>
              <input id="output" name="output" data-help="output" value="outputs\预充值卡商户跑路风险预警输出.xlsx">
            </div>
            <div>
              <label for="pageCount">每页数量</label>
              <input id="pageCount" name="pageCount" data-help="pageCount" type="number" min="1" max="20" value="20">
            </div>
            <div>
              <label for="maxPages">最多页数</label>
              <input id="maxPages" name="maxPages" data-help="maxPages" type="number" min="1" value="200">
            </div>
            <div>
              <label for="llmWorkers">模型并发</label>
              <input id="llmWorkers" name="llmWorkers" data-help="llmWorkers" type="number" min="1" value="4">
            </div>
            <div>
              <label for="sleep">翻页间隔秒</label>
              <input id="sleep" name="sleep" data-help="sleep" type="number" step="0.1" min="0" value="0.2">
            </div>
            <div class="full">
              <label for="modelUrl">大模型接口</label>
              <input id="modelUrl" name="modelUrl" data-help="modelUrl" placeholder="留空使用 .env">
            </div>
            <div>
              <label for="modelName">模型名称</label>
              <input id="modelName" name="modelName" data-help="modelName" placeholder="留空使用 .env">
            </div>
            <div>
              <label for="modelKey">模型 Key</label>
              <input id="modelKey" name="modelKey" data-help="modelKey" type="password" placeholder="留空使用 .env">
            </div>
            <div>
              <label for="targetCity">目标城市</label>
              <input id="targetCity" name="targetCity" data-help="targetCity" value="无锡市">
            </div>
            <div>
              <label for="targetProvince">目标省份</label>
              <input id="targetProvince" name="targetProvince" data-help="targetProvince" value="江苏省">
            </div>
            <div class="full">
              <label for="districts">辖区关键词</label>
              <input id="districts" name="districts" data-help="districts" value="梁溪区,锡山区,惠山区,滨湖区,新吴区,江阴市,宜兴市,经开区,无锡">
            </div>
            <div>
              <label for="fuzzyThreshold">模糊去重阈值</label>
              <input id="fuzzyThreshold" name="fuzzyThreshold" data-help="fuzzyThreshold" type="number" step="0.01" min="0" max="1" value="0.90">
            </div>
            <div>
              <label for="payloadFormat">请求格式</label>
              <select id="payloadFormat" name="payloadFormat" data-help="payloadFormat">
                <option value="json">json</option>
                <option value="form">form</option>
              </select>
            </div>
            <div class="check-row">
              <input id="includeFiltered" name="includeFiltered" data-help="includeFiltered" type="checkbox">
              <label for="includeFiltered">输出过滤记录</label>
            </div>
            <div class="check-row">
              <input id="excludeSuspected" name="excludeSuspected" data-help="excludeSuspected" type="checkbox">
              <label for="excludeSuspected">排除存疑线索</label>
            </div>
            <div class="check-row">
              <input id="disableLlm" name="disableLlm" data-help="disableLlm" type="checkbox">
              <label for="disableLlm">关闭大模型</label>
            </div>
          </div>
          <div class="actions">
            <button id="runBtn" type="submit">开始运行</button>
            <button class="secondary" id="clearBtn" type="button">清空日志</button>
          </div>
        </form>
      </div>
    </section>
    <section>
      <div class="panel-head">
        <h2>运行日志</h2>
        <div class="file-row" id="fileRow"></div>
      </div>
      <pre class="log" id="logBox"></pre>
    </section>
  </main>
  <script>
    const help = __HELP__;
    const form = document.getElementById('runForm');
    const task = document.getElementById('task');
    const output = document.getElementById('output');
    const paramHelp = document.getElementById('paramHelp');
    const logBox = document.getElementById('logBox');
    const jobStatus = document.getElementById('jobStatus');
    const fileRow = document.getElementById('fileRow');
    const runBtn = document.getElementById('runBtn');
    let timer = null;
    let activeJob = null;

    function updateTaskDefaults() {
      const isRaw = task.value === 'raw';
      document.getElementById('analysisMode').disabled = isRaw;
      document.getElementById('includeFiltered').disabled = isRaw;
      document.getElementById('excludeSuspected').disabled = isRaw;
      document.getElementById('disableLlm').disabled = isRaw;
      document.getElementById('targetCity').disabled = isRaw;
      document.getElementById('targetProvince').disabled = isRaw;
      document.getElementById('districts').disabled = isRaw;
      document.getElementById('fuzzyThreshold').disabled = isRaw;
      if (isRaw && output.value.includes('预充值卡商户跑路风险预警输出')) output.value = 'outputs\\舆情API原始结果.xlsx';
      if (!isRaw && output.value.includes('舆情API原始结果')) output.value = 'outputs\\预充值卡商户跑路风险预警输出.xlsx';
    }

    document.querySelectorAll('[data-help]').forEach(el => {
      const show = () => { paramHelp.textContent = help[el.dataset.help] || ''; };
      el.addEventListener('focus', show);
      el.addEventListener('mouseenter', show);
    });
    task.addEventListener('change', updateTaskDefaults);
    updateTaskDefaults();

    document.getElementById('clearBtn').addEventListener('click', () => {
      logBox.textContent = '';
      fileRow.innerHTML = '';
    });

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      runBtn.disabled = true;
      logBox.textContent = '';
      fileRow.innerHTML = '';
      jobStatus.textContent = '启动中';
      const data = Object.fromEntries(new FormData(form).entries());
      data.includeFiltered = document.getElementById('includeFiltered').checked;
      data.excludeSuspected = document.getElementById('excludeSuspected').checked;
      data.disableLlm = document.getElementById('disableLlm').checked;
      const response = await fetch('/api/run', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
      const payload = await response.json();
      if (!response.ok) {
        jobStatus.textContent = '启动失败';
        logBox.textContent = payload.error || '启动失败';
        runBtn.disabled = false;
        return;
      }
      activeJob = payload.job_id;
      pollJob();
      timer = setInterval(pollJob, 1000);
    });

    async function pollJob() {
      if (!activeJob) return;
      const response = await fetch('/api/jobs/' + activeJob);
      const job = await response.json();
      jobStatus.textContent = job.status;
      logBox.textContent = job.logs.join('');
      logBox.scrollTop = logBox.scrollHeight;
      if (job.output) {
        const encoded = encodeURIComponent(job.output);
        fileRow.innerHTML = '<span>' + job.output + '</span><a href="/download?path=' + encoded + '">下载</a>';
      }
      if (job.status === 'finished' || job.status === 'failed') {
        clearInterval(timer);
        timer = null;
        runBtn.disabled = false;
      }
    }

    fetch('/api/env').then(r => r.json()).then(data => {
      document.getElementById('envStatus').textContent = data.env_exists ? '.env 已加载' : '.env 已创建，请配置密钥';
    });
  </script>
</body>
</html>
"""


def json_response(handler: BaseHTTPRequestHandler, data: Dict[str, Any], status: int = 200) -> None:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def text_response(handler: BaseHTTPRequestHandler, text: str, content_type: str = "text/html; charset=utf-8") -> None:
    body = text.encode("utf-8")
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def safe_output_path(value: str) -> Path:
    raw = (value or "").strip()
    if not raw:
        raise ValueError("输出路径不能为空")
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return path


def add_optional(args: List[str], flag: str, value: Any) -> None:
    if value not in (None, ""):
        args.extend([flag, str(value)])


def build_command(params: Dict[str, Any]) -> List[str]:
    task = params.get("task")
    if task == "raw":
        script = ROOT / "scripts" / "export_yuqing_api.py"
        args = [sys.executable, str(script)]
    elif task == "risk":
        script = ROOT / "suyiyu_prepaid_risk.py"
        args = [sys.executable, str(script)]
        add_optional(args, "--analysis-mode", params.get("analysisMode") or "gpu")
        if params.get("includeFiltered"):
            args.append("--include-filtered")
        if params.get("excludeSuspected"):
            args.append("--exclude-suspected")
        if params.get("disableLlm"):
            args.append("--disable-llm")
        add_optional(args, "--target-city", params.get("targetCity"))
        add_optional(args, "--target-province", params.get("targetProvince"))
        add_optional(args, "--districts", params.get("districts"))
        add_optional(args, "--fuzzy-threshold", params.get("fuzzyThreshold"))
        add_optional(args, "--llm-workers", params.get("llmWorkers"))
        add_optional(args, "--model-url", params.get("modelUrl"))
        add_optional(args, "--model-key", params.get("modelKey"))
        add_optional(args, "--model-name", params.get("modelName"))
    else:
        raise ValueError("未知任务类型")

    output_path = safe_output_path(str(params.get("output") or ""))
    add_optional(args, "--output", output_path)
    add_optional(args, "--theme-name", params.get("themeName"))
    add_optional(args, "--news-type", params.get("newsType"))
    add_optional(args, "--attribute", params.get("attribute"))
    add_optional(args, "--date-type", params.get("dateType"))
    add_optional(args, "--begin-date", params.get("beginDate"))
    add_optional(args, "--end-date", params.get("endDate"))
    add_optional(args, "--page-count", params.get("pageCount"))
    add_optional(args, "--max-pages", params.get("maxPages"))
    add_optional(args, "--sleep", params.get("sleep"))
    add_optional(args, "--payload-format", params.get("payloadFormat"))
    return args


def redact_command(cmd: List[str]) -> str:
    redacted = list(cmd)
    for index, part in enumerate(redacted[:-1]):
        if part in {"--model-key", "--app-key", "--secure-key"}:
            redacted[index + 1] = "***"
    return " ".join(redacted)


def run_job(job_id: str, cmd: List[str], output: str) -> None:
    with JOBS_LOCK:
        JOBS[job_id]["status"] = "running"
        JOBS[job_id]["logs"].append("命令: " + redact_command(cmd) + "\n")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        process = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        assert process.stdout is not None
        for line in process.stdout:
            with JOBS_LOCK:
                JOBS[job_id]["logs"].append(line)
        code = process.wait()
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "finished" if code == 0 else "failed"
            JOBS[job_id]["logs"].append(f"进程退出码: {code}\n")
            JOBS[job_id]["output"] = output
    except Exception as exc:
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "failed"
            JOBS[job_id]["logs"].append(f"运行失败: {exc}\n")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            text_response(self, HTML.replace("__HELP__", json.dumps(PARAM_HELP, ensure_ascii=False)))
            return
        if parsed.path == "/api/env":
            env_path = ROOT / ".env"
            json_response(self, {"env_exists": env_path.exists()})
            return
        if parsed.path.startswith("/api/jobs/"):
            job_id = parsed.path.rsplit("/", 1)[-1]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                if not job:
                    json_response(self, {"error": "job not found"}, 404)
                    return
                json_response(self, job)
            return
        if parsed.path == "/download":
            query = parse_qs(parsed.query)
            path = safe_output_path(query.get("path", [""])[0])
            try:
                resolved = path.resolve()
                resolved.relative_to(ROOT.resolve())
            except Exception:
                json_response(self, {"error": "非法下载路径"}, 400)
                return
            if not resolved.exists():
                json_response(self, {"error": "文件不存在"}, 404)
                return
            body = resolved.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            self.send_header("Content-Disposition", f'attachment; filename="{resolved.name}"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        json_response(self, {"error": "not found"}, 404)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/run":
            json_response(self, {"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            params = json.loads(self.rfile.read(length).decode("utf-8"))
            cmd = build_command(params)
            output = str(safe_output_path(str(params.get("output") or "")))
        except Exception as exc:
            json_response(self, {"error": str(exc)}, 400)
            return
        job_id = uuid.uuid4().hex
        with JOBS_LOCK:
            JOBS[job_id] = {"id": job_id, "status": "queued", "logs": [], "output": output, "created_at": time.time()}
        thread = threading.Thread(target=run_job, args=(job_id, cmd, output), daemon=True)
        thread.start()
        json_response(self, {"job_id": job_id})


def main() -> int:
    parser = argparse.ArgumentParser(description="苏移舆情预充值风险本地 Web 控制台")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Web 控制台已启动: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Web 控制台已停止")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
