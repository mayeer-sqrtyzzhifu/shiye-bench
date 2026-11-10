"""指标结果的机器可读输出。

每个评测脚本跑完都写一份到 ``data/results/<dim>.json``，``bench.py`` 再汇总。

为什么要这个：脚本的人类可读报告格式会变，但**数字的口径不该跟着变**。
把结果单独落成 JSON，汇总、对比、画趋势都不必再解析 markdown。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "data" / "results"


def write_result(dim: str, metrics: dict, *, provider: str = "", extra: dict | None = None) -> Path:
    from runners.shiye_lib import shiye_rev

    RESULTS.mkdir(parents=True, exist_ok=True)
    payload = {
        "dim": dim,
        "provider": provider,
        "shiye_rev": shiye_rev(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "metrics": metrics,
    }
    if extra:
        payload.update(extra)
    path = RESULTS / f"{dim}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def read_result(dim: str) -> dict | None:
    path = RESULTS / f"{dim}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
