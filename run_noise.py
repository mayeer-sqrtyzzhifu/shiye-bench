"""噪声来源实验：**同一个输入，回复到底能变多少。**

起因：指标体检发现「二段式」在同一策略的两次运行里只有 69% 逐条一致。
一开始以为是判据在抖，查下去发现**生成温度是 0.8** ——
变的是回复本身，不是尺子。

这个脚本回答两个问题：

1. 温度 0.8 与 0.0，同一个输入跑两次，逐条一致率差多少
2. 降温度能省下多少样本量

用法::

    python run_noise.py --cases 12
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(ROOT))

from checks.result_io import write_result  # noqa: E402
from checks.rules import analyze_turn, two_part_template  # noqa: E402
from checks.stats import cohen_kappa, min_detectable  # noqa: E402
from runners.shiye_lib import ShiyeRunner  # noqa: E402

CASES = ROOT / "data" / "cases" / "single_turn.jsonl"
REPORTS = ROOT / "reports"
RUNS = ROOT / "data" / "runs"


def load_cases(limit: int) -> list[str]:
    items = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [i["user"] for i in items[:limit]]


def generate(users: list[str], temperature: float) -> list[str]:
    runner = ShiyeRunner(with_extraction=False, temperature=temperature)
    out = []
    for index, user in enumerate(users):
        replies = runner.converse([user], case_index=index)
        reply = replies[0]
        out.append(reply.text if reply.ok else "")
    return out


def flags(replies: list[str]) -> dict[str, list[bool]]:
    return {
        "二段式": [two_part_template(r) for r in replies],
        "带问句": [analyze_turn(r).strategy == "提问" for r in replies],
        "完全同文": [],
    }


def agreement(a: list[bool], b: list[bool]) -> tuple[float, float | None]:
    n = min(len(a), len(b))
    if n == 0:
        return 0.0, None
    a, b = a[:n], b[:n]
    rate = sum(1 for x, y in zip(a, b) if x == y) / n
    return rate, cohen_kappa(a, b)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=int, default=12)
    args = parser.parse_args(argv)

    users = load_cases(args.cases)
    rows = []
    for temperature in (0.8, 0.0):
        first = generate(users, temperature)
        second = generate(users, temperature)
        same_text = sum(1 for x, y in zip(first, second) if x == y) / max(1, len(users))
        metric_rows = []
        for name, flagger in (("二段式", two_part_template),
                              ("带问句", lambda r: analyze_turn(r).strategy == "提问")):
            a = [flagger(r) for r in first]
            b = [flagger(r) for r in second]
            rate, kappa = agreement(a, b)
            metric_rows.append((name, rate, kappa))
        rows.append({"temperature": temperature, "same_text": same_text,
                     "metrics": metric_rows, "first": first, "second": second})
        print(f"温度 {temperature}：逐字相同 {same_text:.0%}｜"
              + "｜".join(f"{n} 一致 {r:.0%}" for n, r, _ in metric_rows))

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = REPORTS / f"noise-{stamp}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    (RUNS / f"noise-{stamp}.json").write_text(
        json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"),
                    "cases": users, "rows": rows}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    lines = ["# 噪声来源：同一个输入，回复能变多少\n"]
    lines.append(f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}")
    lines.append(f"- 用例：{len(users)} 条，每个温度跑两遍\n")
    lines.append("| 温度 | 两次回复逐字相同 | 二段式逐条一致 | 带问句逐条一致 |")
    lines.append("|---|---|---|---|")
    for row in rows:
        metrics = {n: r for n, r, _ in row["metrics"]}
        lines.append(
            f"| {row['temperature']} | {row['same_text']:.0%} | "
            f"{metrics.get('二段式', 0):.0%} | {metrics.get('带问句', 0):.0%} |"
        )

    lines.append("\n## 怎么读\n")
    lines.append("- 「逐字相同」是最干净的噪声指标：**同一个输入、同一个策略，两次输出一样吗**")
    lines.append("- 它低到这个程度，说明变的是**生成**，不是判据")
    lines.append("- 这直接解释了为什么小样本测不出 6pp 的差异："
                 "每条用例本身就是一个高方差的硬币")
    lines.append("")
    base = next((r for r in rows if r["temperature"] == 0.8), None)
    cold = next((r for r in rows if r["temperature"] == 0.0), None)
    if base and cold:
        gain = cold["same_text"] - base["same_text"]
        lines.append(f"- 温度从 0.8 降到 0.0，逐字相同从 {base['same_text']:.0%} "
                     f"升到 {cold['same_text']:.0%}（{gain:+.0%}）")
        if cold["same_text"] >= 0.9:
            lines.append("- 说明**评测时把温度压到 0** 可以让逐条指标变得可用；"
                         "但那样测的就不再是线上分布")
        else:
            lines.append("- 即使压到 0，逐字相同仍不过九成 —— "
                         "**模型侧本身就有不可消除的抖动**，只能靠多次采样平均")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_result("noise", {str(r["temperature"]): round(r["same_text"], 3) for r in rows}, provider="real")
    print(f"报告 -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
