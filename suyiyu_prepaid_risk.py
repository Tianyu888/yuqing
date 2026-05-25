#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""兼容入口：实际实现已模块化到 yuqing_prepaid_risk 包。"""

from __future__ import annotations

from yuqing_prepaid_risk.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
