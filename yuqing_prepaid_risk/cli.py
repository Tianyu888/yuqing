from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Optional, Sequence

from .api import fetch_yuqing
from .config import APP_KEY, DEFAULT_LLM_API_KEY, DEFAULT_LLM_API_URL, DEFAULT_LLM_MODEL, DEFAULT_THEME_NAME, SECURE_KEY
from .env import load_env_file
from .io_utils import read_local, write_xlsx
from .pipeline import process_rows
from .utils import log


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    load_env_file()
    parser = argparse.ArgumentParser(description="苏移舆情预充值卡商户跑路风险预警脚本")
    parser.add_argument("--input", type=Path, help="本地输入文件，支持 xlsx/json/csv；不提供则调用 API")
    parser.add_argument("--output", type=Path, default=Path("预充值卡商户跑路风险预警输出.xlsx"))
    parser.add_argument("--include-filtered", action="store_true", help="输出被过滤/去重的记录，便于审计")
    suspected_group = parser.add_mutually_exclusive_group()
    suspected_group.add_argument(
        "--include-suspected",
        dest="include_suspected",
        action="store_true",
        default=True,
        help="将五级不实传言/存疑线索写入最终清单，默认开启",
    )
    suspected_group.add_argument(
        "--exclude-suspected",
        dest="include_suspected",
        action="store_false",
        help="不将五级不实传言/存疑线索写入最终清单",
    )

    parser.add_argument("--app-key", default=os.getenv("SUYIYU_APP_KEY", APP_KEY))
    parser.add_argument("--secure-key", default=os.getenv("SUYIYU_SECURE_KEY", SECURE_KEY))
    parser.add_argument("--theme-name", default=DEFAULT_THEME_NAME, help="专题名称；默认只调用风险研判专题接口")
    parser.add_argument("--news-type", default="all", help="专题接口来源类型 news_type")
    parser.add_argument("--attribute", default="negative", choices=["all", "positive", "neutral", "negative"])
    parser.add_argument("--date-type", type=int, default=7, choices=[0, 1, 7, 30])
    parser.add_argument("--begin-date")
    parser.add_argument("--end-date")
    parser.add_argument("--page-count", type=int, default=20)
    parser.add_argument("--max-pages", type=int, default=200)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--payload-format", choices=["json", "form"], default="json")
    parser.add_argument("--model-url", dest="llm_api_url", default=os.getenv("LLM_API_URL", DEFAULT_LLM_API_URL))
    parser.add_argument("--model-key", dest="llm_api_key", default=os.getenv("LLM_API_KEY", DEFAULT_LLM_API_KEY))
    parser.add_argument("--model-name", "--llm-model", dest="llm_model", default=os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL))
    parser.add_argument("--llm-timeout", type=int, default=120)
    parser.add_argument("--llm-content-chars", type=int, default=5000)
    parser.add_argument(
        "--analysis-mode",
        choices=["cpu", "gpu"],
        default="cpu",
        help="研判模式：cpu=仅本地规则；gpu=CPU规则优先，仅必要时并行调用大模型并做模型辅助去重",
    )
    parser.add_argument("--llm-workers", type=int, default=4, help="大模型并行调用线程数")
    parser.add_argument("--disable-llm", action="store_true", help="关闭大模型语义研判，仅使用本地规则")

    parser.add_argument("--target-city", default="无锡市")
    parser.add_argument("--target-province", default="江苏省")
    parser.add_argument(
        "--districts",
        default="梁溪区,锡山区,惠山区,滨湖区,新吴区,江阴市,宜兴市,经开区,无锡",
        help="辖区关键词，逗号分隔",
    )
    parser.add_argument("--fuzzy-threshold", type=float, default=0.90, help="模糊去重相似度阈值")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    districts = [x.strip() for x in args.districts.split(",") if x.strip()]
    if args.input:
        rows = read_local(args.input)
        log(f"本地舆情读取完成: input={args.input}, rows={len(rows)}")
    else:
        rows = fetch_yuqing(args)

    items, stats = process_rows(
        rows,
        args.target_city,
        args.target_province,
        districts,
        args.fuzzy_threshold,
        args.include_suspected,
        args,
    )
    write_xlsx(items, args.output, args.include_filtered)

    print(f"输入总量: {stats.get('输入总量', 0)}")
    print(f"输出总量: {stats.get('输出总量', 0)}")
    for key in sorted(k for k in stats if k not in {"输入总量", "输出总量"}):
        print(f"{key}: {stats[key]}")
    print(f"输出文件: {args.output}")
    return 0
