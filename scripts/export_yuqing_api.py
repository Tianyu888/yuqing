#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from yuqing_prepaid_risk.config import DEFAULT_THEME_NAME, THEME_API_URL
from yuqing_prepaid_risk.env import load_env_file
from yuqing_prepaid_risk.service import RawExportOptions, export_raw_yuqing


def parse_args() -> argparse.Namespace:
    load_env_file()
    parser = argparse.ArgumentParser(description="直接拉取苏移舆情 API 原始结果并导出 Excel")
    parser.add_argument("--output", type=Path, default=Path("outputs/舆情API原始结果.xlsx"))
    parser.add_argument("--app-key", default=os.getenv("SUYIYU_APP_KEY", ""))
    parser.add_argument("--secure-key", default=os.getenv("SUYIYU_SECURE_KEY", ""))
    parser.add_argument("--url", default=THEME_API_URL)
    parser.add_argument("--theme-name", default=DEFAULT_THEME_NAME)
    parser.add_argument("--news-type", default="all")
    parser.add_argument("--attribute", default="negative", choices=["all", "positive", "neutral", "negative"])
    parser.add_argument("--date-type", type=int, default=7, choices=[0, 1, 7, 30])
    parser.add_argument("--begin-date")
    parser.add_argument("--end-date")
    parser.add_argument("--page-count", type=int, default=20)
    parser.add_argument("--max-pages", type=int, default=200)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--payload-format", choices=["json", "form"], default="json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = export_raw_yuqing(RawExportOptions(**vars(args)))
    print(f"舆情 API 原始结果导出完成: rows={result['row_count']}")
    print(f"输出文件: {result['output']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
