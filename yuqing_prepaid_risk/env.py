from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterable


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

ENV_TEMPLATE = """# 苏移舆情 API
SUYIYU_APP_KEY=
SUYIYU_SECURE_KEY=

# 大模型 API
LLM_API_URL=
LLM_API_KEY=
LLM_MODEL=
"""


def ensure_env_file(path: Path = ENV_PATH) -> None:
    if not path.exists():
        path.write_text(ENV_TEMPLATE, encoding="utf-8")


def parse_env_file(path: Path = ENV_PATH) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def load_env_file(path: Path = ENV_PATH, override: bool = False) -> Dict[str, str]:
    ensure_env_file(path)
    values = parse_env_file(path)
    for key, value in values.items():
        if override or key not in os.environ:
            os.environ[key] = value
    return values


def update_env_file(updates: Dict[str, str], path: Path = ENV_PATH) -> None:
    ensure_env_file(path)
    existing = parse_env_file(path)
    existing.update({key: value for key, value in updates.items() if value is not None})

    ordered_keys: Iterable[str] = [
        "SUYIYU_APP_KEY",
        "SUYIYU_SECURE_KEY",
        "LLM_API_URL",
        "LLM_API_KEY",
        "LLM_MODEL",
    ]
    lines = [
        "# 苏移舆情 API",
        f"SUYIYU_APP_KEY={existing.get('SUYIYU_APP_KEY', '')}",
        f"SUYIYU_SECURE_KEY={existing.get('SUYIYU_SECURE_KEY', '')}",
        "",
        "# 大模型 API",
        f"LLM_API_URL={existing.get('LLM_API_URL', '')}",
        f"LLM_API_KEY={existing.get('LLM_API_KEY', '')}",
        f"LLM_MODEL={existing.get('LLM_MODEL', '')}",
    ]
    extra_keys = sorted(key for key in existing if key not in set(ordered_keys))
    if extra_keys:
        lines.extend(["", "# 其他配置"])
        lines.extend(f"{key}={existing[key]}" for key in extra_keys)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
