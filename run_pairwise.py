"""成对比较：同一批用户发言，两版回复一对一比。

用它替代「两组比例对比」——后者要每组 855 条才能测出 6pp 的差异，
成对比较不吃基线比例，100–200 对就有分辨力。

默认比的是「当前版 vs 上一版」（p5 vs p4），问的是「哪个更自然、更不像模板」。

用法::

    python run_pairwise.py --pairs 40
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(ROOT))

from checks.result_io import write_result  # noqa: E402
from judge.pairwise import judge_pair  # noqa: E402
from runners.shiye_lib import _ensure_shiye_on_path  # noqa: E402

_ensure_shiye_on_path()
from companion.provider import OpenAICompatProvider  # noqa: E402

RUNS = ROOT / "data" / "runs"
REPORTS = ROOT / "reports"
SEED = 20261110

QUESTION = "让人觉得这是一个真人在说话（而不是套模板、走流程）"


def persona_replies(name: str) -> tuple[list[str], list[str]]:
    """从最新的人格运行里取出两个版本的回复（按用例对齐）。"""
    runs = sorted(RUNS.glob("personas-*.json"))
    if not runs:
        raise SystemExit("没有人格运行结果，先跑 run_personas.py")
    payload = json.loads(runs[-1].read_text(encoding="utf-8"))
    by_name = {p["name"]: p["replies"] for p in payload["personas"]}
    if name not in by_name:
        raise SystemExit(f"{runs[-1].name} 里没有 {name}")
    return payload["cases"], by_name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--left", default="p4-openings")
    parser.add_argument("--right", default="p5-nolife")
    parser.add_argument("--pairs", type=int, default=40)
    args = parser.parse_args(argv)

    cases, by_name = persona_replies(args.left)
    left_replies = by_name.get(args.left, [])
    right_replies = by_name.get(args.right, [])
    if not left_replies or not right_replies:
        raise SystemExit("两个版本都要先跑出来")

    n = min(args.pairs, len(cases), len(left_replies), len(right_replies))
    rng = random.Random(SEED)
    order = list(range(n))
    rng.shuffle(order)

    provider = OpenAICompatProvider()
    results = []
    for index in order:
        user = cases[index]
        left = left_replies[index] or ""
        right = right_replies[index] or ""
        if not left.strip() or not right.strip():
            continue
        # 换位再判一次：两次都指向同一个内容才算数
        _, first = judge_pair(provider, user, left, right, QUESTION, swap=False)
        _, second = judge_pair(provider, user, left, right, QUESTION, swap=True)
        consistent = first == second and first in ("left", "right")
        results.append({
            "index": index,
            "user": user,
            "left": left,
            "right": right,
            "first": first,
            "second": second,
            "winner": first if consistent else ("tie" if first == second else "conflict"),
        })

    valid = [r for r in results if r["winner"] in ("left", "right", "tie")]
    conflicts = sum(1 for r in results if r["winner"] == "conflict")
    left_wins = sum(1 for r in valid if r["winner"] == "left")
    right_wins = sum(1 for r in valid if r["winner"] == "right")
    ties = sum(1 for r in valid if r["winner"] == "tie")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = REPORTS / f"pairwise-{stamp}.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = [f"# 成对比较：{args.left} vs {args.right}\n"]
    lines.append(f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}")
    lines.append(f"- 问题：哪一个回应更好地{QUESTION}？")
    lines.append(f"- 每条都判两次（左右互换），只有两次指向同一方才计入\n")
    lines.append("## 结果\n")
    lines.append("| 项 | 数量 |")
    lines.append("|---|---|")
    lines.append(f"| 可比对数 | {len(valid)} |")
    lines.append(f"| {args.right} 胜 | {right_wins} |")
    lines.append(f"| {args.left} 胜 | {left_wins} |")
    lines.append(f"| 平局 | {ties} |")
    lines.append(f"| 位置不一致（不计） | {conflicts} |")
    lines.append("")

    decided = left_wins + right_wins
    if decided:
        share = right_wins / decided
        lines.append(f"**在有胜负的 {decided} 对里，{args.right} 胜 {share:.0%}。**\n")
        lines.append("> 成对比较不看基线比例，50% 就是「没有差别」。")
        lines.append("> 95% 区间可以用二项分布估；这里不展开，样本够时再看。")
    if conflicts:
        lines.append(f"\n> ⚠️ {conflicts} 对在左右互换后给出了相反答案 —— "
                     "说明判据对这些样本没有稳定偏好，不该计入。")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_result("pairwise", {
        "left": args.left, "right": args.right,
        "left_wins": left_wins, "right_wins": right_wins,
        "ties": ties, "conflicts": conflicts,
    }, provider="real")
    print(f"报告 -> {out.relative_to(ROOT)}")
    print(f"{args.right} {right_wins}｜{args.left} {left_wins}｜平 {ties}｜不一致 {conflicts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
