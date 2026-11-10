"""对已保存的运行结果重算规则，不调用模型。

改判据是高频动作，改一次就重跑一次模型太浪费。``run.py`` 会把原始回复
落盘到 ``data/runs/``，这里读回来重新判定，几秒钟出结果。

用法::

    python scripts/reanalyze.py                     # 用最新一次运行
    python scripts/reanalyze.py data/runs/xxx.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from checks.rules import analyze_turn, session_findings  # noqa: E402

RUNS = ROOT / "data" / "runs"
REPORTS = ROOT / "reports"


def latest_run() -> Path:
    files = sorted(RUNS.glob("*.json"))
    if not files:
        raise SystemExit("data/runs 里没有结果，先跑 run.py")
    return files[-1]



def reanalyze_arcs(path: Path, payload: dict) -> int:
    """弧用例重算：对已存回复重新打标、重算轨迹指标。"""
    from checks.arcs import aggregate, analyze_arc
    from checks.rules import tag_intensity

    reports = []
    details = []
    for session in payload["sessions"]:
        agent = [analyze_turn(text) for text in session["replies"] if text]
        user_intensity = [tag_intensity(t) for t in session["turns"]][: len(agent)]
        report = analyze_arc(agent, user_intensity)
        reports.append(report)
        details.append((session, agent, report))

    summary = aggregate(reports)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = REPORTS / f"reanalyze-arcs-{path.stem}-{stamp}.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = [f"# 弧用例重算（{payload.get('provider')} · {path.name}）\n"]
    lines.append(f"- 原始运行：{payload.get('generated_at')}")
    lines.append(f"- 重算时间：{datetime.now():%Y-%m-%d %H:%M}\n")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 峰值后回落 | {summary['peak_relief']}/{summary['relief_eligible']} |")
    lines.append(f"| 卡带率 | {summary['stuck_rate']:.0%} |")
    lines.append(f"| 复读率 | {summary['repeat_rate']:.0%} |")
    lines.append(f"| 断崖率 | {summary['jump_rate']:.0%} |")
    lines.append(f"| 抢跑次数 | {summary['lead_count']} |")
    lines.append(f"| 策略多样性 | {summary['diversity']:.2f} |")
    if "two_part_rate" in summary:
        lines.append(f"| 二段式（整体） | {summary['two_part_rate']:.0%} |")
        lines.append(f"| 二段式（开场） | {summary.get('opener_two_part', 0)}/{summary['sessions']} |")
    lines.append("")
    lines.append("| 会话 | 轮数 | 峰值 | 结束 | 回落 | 卡带 | 复读 | 断崖 | 多样性 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for session, _agent, rep in details:
        lines.append(
            f"| {session['id']} | {rep.turns} | {rep.peak_intensity} | {rep.end_intensity} | "
            f"{'✓' if rep.peak_relief else '✗'} | {rep.stuck_rate:.0%} | {rep.repeat_rate:.0%} | "
            f"{rep.jump_rate:.0%} | {rep.diversity:.2f} |"
        )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"报告 -> {out.relative_to(ROOT)}")
    print(
        f"回落 {summary['peak_relief']}/{summary['relief_eligible']}｜"
        f"卡带 {summary['stuck_rate']:.0%}｜复读 {summary['repeat_rate']:.0%}｜"
        f"断崖 {summary['jump_rate']:.0%}｜多样性 {summary['diversity']:.2f}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run", nargs="?", default=None)
    args = parser.parse_args(argv)

    path = Path(args.run) if args.run else latest_run()
    payload = json.loads(path.read_text(encoding="utf-8"))

    if "sessions" in payload:
        return reanalyze_arcs(path, payload)

    rows = []
    for item in payload["cases"]:
        features = analyze_turn(item["reply"]) if item["ok"] and item["reply"] else None
        rows.append({"item": item, "features": features})

    ok_rows = [r for r in rows if r["features"]]
    lengths = [r["features"].length for r in ok_rows]
    questions = [r["features"].questions for r in ok_rows]
    strategy = Counter(r["features"].strategy for r in ok_rows)
    intensity = Counter(r["features"].intensity for r in ok_rows)
    findings = Counter(f.code for r in ok_rows for f in r["features"].findings)
    for item in session_findings([r["features"] for r in ok_rows], same_conversation=False):
        findings[item.code] += 1
    interjection = sum(1 for r in ok_rows if r["features"].starts_with_interjection)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = REPORTS / f"reanalyze-{path.stem}-{stamp}.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = [f"# 重算报告（{payload.get('provider')} · {path.name}）\n"]
    lines.append(f"- 原始运行：{payload.get('generated_at')}")
    lines.append(f"- 重算时间：{datetime.now():%Y-%m-%d %H:%M}")
    lines.append(f"- 用例数：{len(rows)}\n")

    lines.append("## 汇总\n")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    if lengths:
        lines.append(f"| 平均长度 | {sum(lengths) / len(lengths):.1f} 字 |")
        lines.append(f"| 平均问句 | {sum(questions) / len(questions):.2f} |")
        lines.append(f"| 以语气词开头 | {interjection}/{len(ok_rows)} |")
    lines.append(f"| 策略分布 | {dict(strategy)} |")
    lines.append(f"| 强度分布 | {dict(intensity)} |")
    lines.append(f"| 规则命中 | {dict(findings) or '无'} |")
    lines.append("")

    lines.append("## 逐条\n")
    lines.append("| # | 用户 | 回复 | 长度 | 问句 | 策略 | 强度 | 规则命中 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for row in rows:
        item, features = row["item"], row["features"]
        user_text = item["user"].replace("|", "｜")[:40]
        if features:
            reply_text = features.text.replace("|", "｜").replace("\n", " ")[:60]
            codes = ", ".join(f.code for f in features.findings) or "-"
            lines.append(
                f"| {item['id']} | {user_text} | {reply_text} | {features.length} | "
                f"{features.questions} | {features.strategy} | {features.intensity} | {codes} |"
            )
        else:
            lines.append(f"| {item['id']} | {user_text} | ⚠️ {item.get('notes')} | - | - | - | - | - |")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"报告 -> {out.relative_to(ROOT)}")
    print(f"策略分布 {dict(strategy)}")
    print(f"规则命中 {sum(findings.values())} 次")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
