"""从 SmileChat 构造多轮"情绪弧"用例。

和单轮用例的区别：弧用例关心的是**情绪随时间怎么走**——承接、停留、松动、转场。
所以它需要一串连贯的用户发言，而不是一句开场。

做法：从同一段真实对话里抽取来访者的多轮发言，过滤掉依赖咨询师前文的那些
（"您说得对""谢谢您的建议"），剩下的构成一条自驱的情绪线。

局限（必须写清楚）：这些发言原本是对着咨询师说的，中间的衔接在语义上会
有些跳跃。它测的是**agent 在连续情绪变化下的稳定性**（会不会复读、会不会
一直顶在峰值），不是"对话是否自然流畅"——后者需要合成脚本，另做。

用法::

    python scripts/make_arcs.py --count 6 --max-turns 6
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
OUT = ROOT / "data" / "cases" / "arcs.jsonl"
SEED = 20261110

_CJK = re.compile(r"[\u4e00-\u9fff]")

# 依赖咨询师前文的发言，拿掉
_DEPENDENT = re.compile(
    r"您说|你说得对|你说的|老师说|感谢|谢谢|您的建议|听您|按您|我会努力|我会尝试"
)


def _len(text: str) -> int:
    return len(_CJK.findall(text)) + len(re.sub(r"[\u4e00-\u9fff\s]", "", text))


def extract_arcs(min_turns: int, max_turns: int) -> list[list[str]]:
    arcs: list[list[str]] = []
    for path in sorted(DATA_DIR.glob("*.json")):
        try:
            dialog = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue

        turns: list[str] = []
        for turn in dialog:
            if turn.get("role") != "client":
                continue
            text = " ".join(str(turn.get("content", "")).split())
            if not (6 <= _len(text) <= 160):
                continue
            if _DEPENDENT.search(text):
                continue
            turns.append(text)

        if len(turns) >= min_turns:
            arcs.append(turns[:max_turns])
    return arcs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=6)
    parser.add_argument("--min-turns", type=int, default=5)
    parser.add_argument("--max-turns", type=int, default=6)
    args = parser.parse_args(argv)

    if not DATA_DIR.exists():
        print("先跑 scripts/fetch_smilechat.py", file=sys.stderr)
        return 2

    arcs = extract_arcs(args.min_turns, args.max_turns)
    if not arcs:
        print("没有满足条件的长对话，放宽 --min-turns 试试", file=sys.stderr)
        return 2

    rng = random.Random(SEED)
    picked = rng.sample(arcs, min(args.count, len(arcs)))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as handle:
        for index, turns in enumerate(picked):
            handle.write(json.dumps(
                {"id": f"arc-{index:02d}", "source": "smilechat", "turns": turns},
                ensure_ascii=False,
            ) + "\n")

    lengths = [len(t) for t in picked]
    print(f"可用长对话 {len(arcs)} 段，采样 {len(picked)} 段 -> {OUT.relative_to(ROOT)}")
    print(f"每段轮数：{lengths}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
