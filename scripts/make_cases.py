"""从 SmileChat 采样生成单轮用例。

单轮用例是**最小可跑单元**：先验证规则层能对真实中文输入给出稳定判定，
再往多轮弧扩展。不要一上来就做 12 轮会话——链路没通之前，多轮只会放大噪声。

筛选口径：
* 长度 8–120 字（太短没有信息量，太长不像即时聊天）
* **只取开场**：中间轮次依赖前文，单拎出来会驴唇不对马嘴
* **排除对话结尾**：SmileChat 每段最后 1–2 轮几乎都是"谢谢您，我会努力"这类
  收尾致谢，拿来当开场会让所有回复都驴唇不对马嘴
* 排除致谢/总结式句子（正则）
* 去重
* 固定 seed，可复现

用法::

    python scripts/make_cases.py --count 30
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "smilechat"
OUT = ROOT / "data" / "cases" / "single_turn.jsonl"
SEED = 20261110

_CJK = re.compile(r"[\u4e00-\u9fff]")

# 收尾/致谢句式：这些轮次适合当"对话结束"，不适合当新场景的开场
_CLOSING = re.compile(
    r"谢谢|感谢|我会努力|我会牢记|受益匪浅|非常感谢|谢谢您|谢谢你的|感谢你|"
    r"再次感谢|祝您|祝你|辛苦您|辛苦了老师"
)


def _len(text: str) -> int:
    return len(_CJK.findall(text)) + len(re.sub(r"[\u4e00-\u9fff\s]", "", text))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--min-len", type=int, default=8)
    parser.add_argument("--max-len", type=int, default=120)
    args = parser.parse_args(argv)

    if not DATA_DIR.exists():
        print("先跑 scripts/fetch_smilechat.py", file=sys.stderr)
        return 2

    candidates: list[str] = []
    seen: set[str] = set()
    for path in sorted(DATA_DIR.glob("*.json")):
        try:
            dialog = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        # 单轮用例只取**开头的来访者发言**：中间轮次依赖前文，
        # 单独拿出来问会显得莫名其妙（"是的，我觉得在公司…"这种）
        head = dialog[:3]
        for turn in head:
            if turn.get("role") != "client":
                continue
            text = " ".join(str(turn.get("content", "")).split())
            if not (args.min_len <= _len(text) <= args.max_len):
                continue
            if _CLOSING.search(text):
                continue
            if text in seen:
                continue
            seen.add(text)
            candidates.append(text)

    if not candidates:
        print("没有符合条件的候选", file=sys.stderr)
        return 2

    rng = random.Random(SEED)
    picked = rng.sample(candidates, min(args.count, len(candidates)))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as handle:
        for index, text in enumerate(picked):
            handle.write(json.dumps(
                {"id": f"st-{index:03d}", "source": "smilechat", "user": text},
                ensure_ascii=False,
            ) + "\n")

    print(f"候选 {len(candidates)} 条，采样 {len(picked)} 条 -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
