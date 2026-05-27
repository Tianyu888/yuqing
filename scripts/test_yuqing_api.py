#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from yuqing_prepaid_risk.config import DEFAULT_THEME_NAME, THEME_API_URL
from yuqing_prepaid_risk.env import load_env_file, update_env_file
from yuqing_prepaid_risk.service import YuqingApiTestOptions, test_yuqing_api


def prompt_value(label: str, current: str = "") -> str:
    suffix = "，直接回车使用当前值" if current else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or current


def main() -> int:
    env = load_env_file()
    parser = argparse.ArgumentParser(description="测试苏移舆情 API 连通性")
    parser.add_argument("--app-key", default=env.get("SUYIYU_APP_KEY", ""))
    parser.add_argument("--secure-key", default=env.get("SUYIYU_SECURE_KEY", ""))
    parser.add_argument("--url", default=THEME_API_URL)
    parser.add_argument("--theme-name", default=DEFAULT_THEME_NAME)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--payload-format", choices=["json", "form"], default="json")
    args = parser.parse_args()

    app_key = args.app_key or prompt_value("请输入 SUYIYU_APP_KEY")
    secure_key = args.secure_key or prompt_value("请输入 SUYIYU_SECURE_KEY")
    if not app_key or not secure_key:
        print("缺少 SUYIYU_APP_KEY 或 SUYIYU_SECURE_KEY")
        return 2

    try:
        result = test_yuqing_api(
            YuqingApiTestOptions(
                app_key=app_key,
                secure_key=secure_key,
                url=args.url,
                theme_name=args.theme_name,
                timeout=args.timeout,
                payload_format=args.payload_format,
            )
        )
    except Exception as exc:
        print(f"舆情 API 测试失败: {exc}")
        return 1

    print("舆情 API 测试通过。")
    print(f"返回字段: {', '.join(result['fields'])}")
    answer = input("是否将本次 SUYIYU_APP_KEY/SUYIYU_SECURE_KEY 写入 .env？[y/N]: ").strip().lower()
    if answer in {"y", "yes", "是"}:
        update_env_file({"SUYIYU_APP_KEY": app_key, "SUYIYU_SECURE_KEY": secure_key})
        print(".env 已更新。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
