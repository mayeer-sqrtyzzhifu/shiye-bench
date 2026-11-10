"""指标体检：每个指标到底能不能信。

对每条**逐用例**的判定，用同一策略跑两次，量三件事：

1. **重测一致**（同一策略、同一用例，两次判定是否一样）
   —— 低了一致说明指标本身在抖，聚合出来的比例不可信
2. **κ**（扣掉「瞎猜也能碰上」的那部分）
3. **可测下限**（这个样本量下能分辨多大的差异）

结论会分成三档：`可用` / `只可信聚合` / `不可用`。

用法::

    python run_metrics_audit.py --runs data/runs/real-A.json data/runs/real-B.json
    python run_metrics_audit.py            # 自动取同一 shiye 版本下最新的两次
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(ROOT))

from checks.result_io import write_result  # noqa: E402
from checks.rules import (  # noqa: E402
    analyze_turn,
    check_invented_life,
    two_part_template,
)
from checks.stats import cohen_kappa, min_detectable, wilson  # noqa: E402

RUNS = ROOT / "data" / "runs"
REPORTS = ROOT / "reports"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def per_case_flags(payload: dict) -> dict[str, list[bool]]:
    """把一次运行折算成「每个指标、每条用例」的布尔序列。"""
    flags: dict[str, list[bool]] = {
        "二段式": [],
        "超长(>80)": [],
        "带问句": [],
        "编造生活": [],
        "语气词开头": [],
    }
    for case in payload["cases"]:
        if not (case.get("ok") and case.get("reply")):
            continue
        text = case["reply"]
        features = analyze_turn(text)
        flags["二段式"].append(two_part_template(text))
        flags["超长(>80)"].append(features.length > 80)
        flags["带问句"].append(features.strategy == "提问")
        flags["编造生活"].append(bool(check_invented_life(text)))
        flags["语气词开头"].append(features.starts_with_interjection)
    return flags


def align(a: dict, b: dict) -> list[str]:
    """取两次运行共有的用例 id，保证逐条对齐。"""
    ids_a = [c["id"] for c in a["cases"] if c.get("ok") and c.get("reply")]
    ids_b = {c["id"] for c in b["cases"] if c.get("ok") and c.get("reply")}
    return [i for i in ids_a if i in ids_b]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", nargs="*", default=None)
    args = parser.parse_args(argv)

    if args.runs and len(args.runs) >= 2:
        paths = [Path(p) for p in args.runs[:2]]
    else:
        # 自动找：同一 shiye 版本、最新的两次单轮运行
        by_rev: dict[str, list[Path]] = {}
        for path in sorted(RUNS.glob("real-*.json")):
            payload = load(path)
            rev = payload.get("shiye_rev") or "unknown"
            by_rev.setdefault(rev, []).append(path)
        candidates = [(rev, ps) for rev, ps in by_rev.items() if len(ps) >= 2]
        if not candidates:
            raise SystemExit("找不到同一版本下的两次运行；先跑两遍 run.py --provider real")
        rev, paths = max(candidates, key=lambda item: len(item[1]))
        paths = paths[-2:]
        print(f"用 shiye @ {rev} 的两次运行：{[p.name for p in paths]}")

    a, b = load(paths[0]), load(paths[1])
    ids = align(a, b)
    if len(ids) < 10:
        raise SystemExit(f"两次运行只有 {len(ids)} 条对得上，太少")

    flags_a = per_case_flags(a)
    flags_b = per_case_flags(b)

    rows = []
    for metric in flags_a:
        series_a = flags_a[metric]
        series_b = flags_b[metric]
        n = min(len(series_a), len(series_b))
        series_a, series_b = series_a[:n], series_b[:n]
        agree = sum(1 for x, y in zip(series_a, series_b) if x == y) / n
        kappa = cohen_kappa(series_a, series_b)
        rate = (sum(series_a) + sum(series_b)) / (2 * n)
        lo, hi = wilson(int(rate * 2 * n), 2 * n)
        floor = min_detectable(max(rate, 0.01), n)

        if kappa is None:
            # 两次都只用了一个类别：一致率再高也没有信息，不能说"可用"
            verdict = "从不触发（无法判断）" if sum(series_a) == 0 and sum(series_b) == 0 else "样本不足"
        elif kappa >= 0.6 and agree >= 0.85:
            verdict = "可用（逐条）"
        elif agree >= 0.75:
            verdict = "只可信聚合"
        else:
            verdict = "不稳定"
        rows.append({
            "metric": metric,
            "rate": rate,
            "ci": (lo, hi),
            "agree": agree,
            "kappa": kappa,
            "floor": floor,
            "verdict": verdict,
        })

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = REPORTS / f"metrics-audit-{stamp}.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = ["# 指标体检：每个指标能不能信\n"]
    lines.append(f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}")
    lines.append(f"- 数据：同一策略的两次运行（{paths[0].name} / {paths[1].name}）")
    lines.append(f"- 对齐用例：**{len(ids)} 条**\n")
    lines.append("## 结果\n")
    lines.append("| 指标 | 出现率 | 95% CI | 重测一致 | κ | 可测下限 | 结论 |")
    lines.append("|---|---|---|---|---|---|---|")
    for row in rows:
        lo, hi = row["ci"]
        kappa = "—" if row["kappa"] is None else f"{row['kappa']:.2f}"
        lines.append(
            f"| {row['metric']} | {row['rate']:.0%} | {lo:.0%}–{hi:.0%} | "
            f"{row['agree']:.0%} | {kappa} | {row['floor']:.0%} | {row['verdict']} |"
        )

    lines.append("\n## 怎么读\n")
    lines.append("- **重测一致**：同一策略、同一用例，两次判定是否相同。"
                 "低了一致说明指标本身在抖")
    lines.append("- **κ**：扣掉「这个指标本来就很少出现，所以很容易一致」的假象")
    lines.append("- **可测下限**：这个样本量下，两组之间能分辨的最小差异。"
                 "它比任何单次结果都重要")
    lines.append("")

    usable = [r for r in rows if r["verdict"].startswith("可用")]
    aggregate = [r for r in rows if r["verdict"] == "只可信聚合"]
    unstable = [r for r in rows if r["verdict"] == "不稳定"]

    lines.append(f"- 逐条可用：{', '.join(r['metric'] for r in usable) or '无'}")
    lines.append(f"- 只可信聚合：{', '.join(r['metric'] for r in aggregate) or '无'}")
    lines.append(f"- 不稳定：{', '.join(r['metric'] for r in unstable) or '无'}")
    lines.append("")
    worst_floor = max((r["floor"] for r in rows), default=0)
    lines.append(
        f"**在当前 {len(ids)} 条的样本量下，任何小于 {worst_floor:.0%} 的差异都测不出来。**"
    )
    lines.append("把这句话记在每份报告旁边，比记分数有用。")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_result("metrics_audit", {
        r["metric"]: {"rate": round(r["rate"], 3), "agree": round(r["agree"], 3),
                      "kappa": None if r["kappa"] is None else round(r["kappa"], 3),
                      "floor": round(r["floor"], 3), "verdict": r["verdict"]}
        for r in rows
    }, provider="real", extra={"n": len(ids)})
    print(f"报告 -> {out.relative_to(ROOT)}")
    for row in rows:
        print(f"  {row['metric']:<10} 一致 {row['agree']:.0%}｜κ "
              f"{'—' if row['kappa'] is None else format(row['kappa'], '.2f')}｜{row['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
