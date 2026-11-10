"""成对判据的三组实验：**先证明它能用，再用它下结论。**

上一轮直接拿 p4 vs p5 去比，结果一半样本换位后答案反转。
那可能是三种情况：

1. 判官有位置偏好（总选 A 或总选 B）
2. 判官对这两版根本没有偏好，在随机选
3. 判据坏了

光看反转率分不出来。所以给它两组对照：

* **明确差异**：真回复 vs 明显不合适的模板。判官必须选中真回复，且换位后仍选中
* **完全相同**：真回复 vs 它自己。判官应当判平局，而不是硬选一边

**对照通过之后，第三组（p4 vs p5）的结论才有意义。**

用法::

    python run_pairwise.py --pairs 12
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

from checks.result_io import wilson, write_result  # noqa: E402
from judge.pairwise import judge_pair  # noqa: E402
from runners.shiye_lib import _ensure_shiye_on_path  # noqa: E402

_ensure_shiye_on_path()
from companion.provider import OpenAICompatProvider  # noqa: E402

RUNS = ROOT / "data" / "runs"
REPORTS = ROOT / "reports"
SEED = 20261110

QUESTION = "让人觉得这是一个真人在说话（而不是套模板、走流程）"

# 明显不合适的对照：套模板、走流程
BAD = [
    "辛苦了，早点休息吧，注意身体。",
    "我完全理解你的感受。建议你可以试试写下来，会好很多。",
    "这确实挺难的，不过你已经很棒了，别给自己太大压力。",
    "往好处想，至少你还有家人支持你呀。",
    "嗯嗯，我懂。对了，你吃饭了吗？",
    "这有什么好难过的，大家都这样过来的。",
]


def personas(name_left: str, name_right: str):
    runs = sorted(RUNS.glob("personas-*.json"))
    if not runs:
        raise SystemExit("没有人格运行结果，先跑 run_personas.py")
    payload = json.loads(runs[-1].read_text(encoding="utf-8"))
    by_name = {p["name"]: p["replies"] for p in payload["personas"]}
    for name in (name_left, name_right):
        if name not in by_name:
            raise SystemExit(f"{runs[-1].name} 里没有 {name}")
    return payload["cases"], by_name


def run_block(provider, pairs: list[dict], label: str) -> dict:
    """每条判两次（左右互换），返回统计。"""
    rows = []
    for item in pairs:
        _, first = judge_pair(provider, item["user"], item["left"], item["right"], QUESTION)
        _, second = judge_pair(provider, item["user"], item["left"], item["right"],
                               QUESTION, swap=True)
        if first and second and first == second:
            outcome = first  # left / right / tie，两次一致
        elif first and second:
            outcome = "conflict"
        else:
            outcome = "error"
        rows.append({**item, "first": first, "second": second, "outcome": outcome})

    valid = [r for r in rows if r["outcome"] not in ("conflict", "error")]
    return {
        "label": label,
        "rows": rows,
        "left": sum(1 for r in valid if r["outcome"] == "left"),
        "right": sum(1 for r in valid if r["outcome"] == "right"),
        "tie": sum(1 for r in valid if r["outcome"] == "tie"),
        "conflict": sum(1 for r in rows if r["outcome"] == "conflict"),
        "error": sum(1 for r in rows if r["outcome"] == "error"),
        "total": len(rows),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--left", default="p4-openings")
    parser.add_argument("--right", default="p5-nolife")
    parser.add_argument("--pairs", type=int, default=12)
    args = parser.parse_args(argv)

    cases, by_name = personas(args.left, args.right)
    rng = random.Random(SEED)
    order = list(range(min(args.pairs, len(cases))))
    rng.shuffle(order)

    def reply(name: str, index: int) -> str:
        values = by_name[name]
        return values[index] if index < len(values) else ""

    provider = OpenAICompatProvider()

    # 控制组一：真回复 vs 明显不合适的模板 —— 必须选中真回复
    clear = []
    for i, index in enumerate(order):
        good = reply(args.right, index)
        if not good.strip():
            continue
        clear.append({"user": cases[index], "left": good, "right": BAD[i % len(BAD)]})
    block_clear = run_block(provider, clear, "明确差异（真回复 vs 模板）")

    # 控制组二：真回复 vs 它自己 —— 应当判平局
    same = []
    for index in order:
        good = reply(args.right, index)
        if not good.strip():
            continue
        same.append({"user": cases[index], "left": good, "right": good})
    block_same = run_block(provider, same, "完全相同（自己 vs 自己）")

    # 目标组：两版人格对比
    target = []
    for index in order:
        left = reply(args.left, index)
        right = reply(args.right, index)
        if not left.strip() or not right.strip():
            continue
        target.append({"user": cases[index], "left": left, "right": right})
    block_target = run_block(provider, target, f"目标（{args.left} vs {args.right}）")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = REPORTS / f"pairwise-{stamp}.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = ["# 成对判据：先过对照，再看结论\n"]
    lines.append(f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}")
    lines.append(f"- 问题：哪一个回应更好地{QUESTION}？")
    lines.append("- 每条判两次（左右互换），两次一致才计入\n")
    lines.append("## 三组结果\n")
    lines.append("| 组 | 左胜 | 右胜 | 平局 | 换位不一致 | 解析失败 | 计入 |")
    lines.append("|---|---|---|---|---|---|---|")
    for block in (block_clear, block_same, block_target):
        counted = block["left"] + block["right"] + block["tie"]
        lines.append(
            f"| {block['label']} | {block['left']} | {block['right']} | {block['tie']} | "
            f"{block['conflict']} | {block['error']} | {counted}/{block['total']} |"
        )

    lines.append("\n## 对照过没过\n")
    clear_ok = block_clear["left"] >= 0.7 * max(1, block_clear["left"] + block_clear["right"] + block_clear["tie"])
    lines.append(
        f"- **明确差异组**：选中真回复 {block_clear['left']}/"
        f"{block_clear['left'] + block_clear['right'] + block_clear['tie']}"
        f" → {'通过' if clear_ok else '**未通过**，判据分辨不了明显差异'}"
    )
    same_tie = block_same["tie"] / max(1, block_same["left"] + block_same["right"] + block_same["tie"])
    lines.append(
        f"- **完全相同组**：判平局 {same_tie:.0%} → "
        f"{'通过' if same_tie >= 0.5 else '**未通过**，对相同的回复也硬选一边'}"
    )

    lines.append("\n## 目标组怎么读\n")
    if not (clear_ok and same_tie >= 0.5):
        lines.append("对照没过，目标组的结论**不能用**。先修判据。")
    else:
        counted = block_target["left"] + block_target["right"] + block_target["tie"]
        conflict_rate = block_target["conflict"] / max(1, block_target["total"])
        lines.append(f"- 换位不一致率：{conflict_rate:.0%}")
        if conflict_rate >= 0.4:
            lines.append("- **一致率太低**：说明这两版在判据眼里没有稳定差别，"
                         "不能据此说谁更好")
        elif counted >= 8:
            lo, hi = wilson(block_target["right"], counted)
            lines.append(f"- {args.right} 胜 {block_target['right']}/{counted}"
                         f"（95% CI {lo:.0%}–{hi:.0%}）")
            if lo > 0.5:
                lines.append(f"- 区间不跨 50%，可以认为 {args.right} 更好")
            elif hi < 0.5:
                lines.append(f"- 区间不跨 50%，可以认为 {args.left} 更好")
            else:
                lines.append("- 区间跨 50%，**分不出谁更好**")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_result("pairwise", {
        "clear": {"left": block_clear["left"], "conflict": block_clear["conflict"]},
        "same": {"tie": block_same["tie"], "total": block_same["total"]},
        "target": {"left": block_target["left"], "right": block_target["right"],
                   "tie": block_target["tie"], "conflict": block_target["conflict"]},
    }, provider="real")
    print(f"报告 -> {out.relative_to(ROOT)}")
    for block in (block_clear, block_same, block_target):
        print(f"  {block['label']}: 左{block['left']} 右{block['right']} "
              f"平{block['tie']} 不一致{block['conflict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
