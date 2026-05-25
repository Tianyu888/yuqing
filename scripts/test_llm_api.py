#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from yuqing_prepaid_risk.env import load_env_file, update_env_file


def prompt_value(label: str, current: str = "") -> str:
    suffix = "，直接回车使用当前值" if current else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or current


def main() -> int:
    env = load_env_file()
    parser = argparse.ArgumentParser(description="测试 OpenAI 兼容大模型 API 连通性")
    parser.add_argument("--model-url", default=env.get("LLM_API_URL", ""))
    parser.add_argument("--model-key", default=env.get("LLM_API_KEY", ""))
    parser.add_argument("--model-name", default=env.get("LLM_MODEL", ""))
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    model_url = args.model_url or prompt_value("请输入 LLM_API_URL")
    model_key = args.model_key or prompt_value("请输入 LLM_API_KEY")
    model_name = args.model_name or prompt_value("请输入 LLM_MODEL")
    if not model_url or not model_key or not model_name:
        print("缺少 LLM_API_URL、LLM_API_KEY 或 LLM_MODEL")
        return 2

    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": "请只回复 OK"}],
    }
    headers = {"Authorization": f"Bearer {model_key}", "Content-Type": "application/json"}
    try:
        response = requests.post(model_url, json=payload, headers=headers, timeout=args.timeout)
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
    except Exception as exc:
        print(f"大模型 API 测试失败: {exc}")
        return 1

    print("大模型 API 测试通过。")
    print(f"模型返回: {content}")
    answer = input("是否将本次 LLM_API_URL/LLM_API_KEY/LLM_MODEL 写入 .env？[y/N]: ").strip().lower()
    if answer in {"y", "yes", "是"}:
        update_env_file({"LLM_API_URL": model_url, "LLM_API_KEY": model_key, "LLM_MODEL": model_name})
        print(".env 已更新。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
