"""跑多轮情绪弧评测。

用法::

    python run_arcs.py --provider fake --limit 6
    python run_arcs.py --provider real --limit 6

和单轮评测的区别：这里看的是**一段对话的走势**，不是单句好坏。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(ROOT))

from checks.arcs import aggregate, analyze_arc  # noqa: E402
from checks.result_io import write_result  # noqa: E402
from checks.rules import analyze_turn, tag_intensity  # noqa: E402
from runners.shiye_lib import ShiyeRunner, fake_provider, shiye_rev  # noqa: E402

ARCS = ROOT / "data" / "cases" / "arcs.jsonl"
REPORTS = ROOT / "reports"
RUNS = ROOT / "data" / "runs"

# 假 provider 的两套剧本：一套"卡带"、一套"会走"，用来验证指标抓得住
STUCK_REPLIES = ["听着是真累。", "听着是真累。", "听着是真累。"]
MOVING_REPLIES = [
    "被这么一说，是挺堵的。",
    "这种事攒久了，人是会乏。",
    "几点了呀，今天还撑得住吗。",
    "先放一放吧，不用今天都解决。",
    "嗯，我在。",
]


def load_arcs(limit: int) -> list[dict]:
    if not ARCS.exists():
        raise SystemExit(f"用例不存在：{ARCS}（先跑 scripts/make_arcs.py）")
    items = [json.loads(line) for line in ARCS.read_text(encoding="utf-8").splitlines() if line.strip()]
    return items[:limit]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("fake", "stuck", "real"), default="fake")
    parser.add_argument("--limit", type=int, default=6)
    args = parser.parse_args(argv)

    # 每段会话用新的 provider：FakeProvider 用完剧本会一直重复最后一条，
    # 复用会让第二段开始的所有回复都变成同一句（假数据反而测出"卡带"）
    def make_runner():
        if args.provider == "stuck":
            return ShiyeRunner(provider=fake_provider(STUCK_REPLIES))
        if args.provider == "fake":
            return ShiyeRunner(provider=fake_provider(MOVING_REPLIES))
        return ShiyeRunner()

    label = {"stuck": "fake(卡带)", "fake": "fake(会走)", "real": "real"}[args.provider]

    arcs = load_arcs(args.limit)
    rows = []
    reports = []
    for index, arc in enumerate(arcs):
        replies = make_runner().converse(arc["turns"], case_index=index)
        agent_features = [analyze_turn(r.text) for r in replies if r.ok and r.text]
        user_intensity = [tag_intensity(t) for t in arc["turns"]][: len(agent_features)]
        report = analyze_arc(agent_features, user_intensity)
        reports.append(report)
        rows.append({"arc": arc, "replies": replies, "features": agent_features, "report": report})

    summary = aggregate(reports)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    RUNS.mkdir(parents=True, exist_ok=True)
    run_file = RUNS / f"arcs-{args.provider}-{stamp}.json"
    run_file.write_text(json.dumps({
        "provider": label,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "shiye_rev": shiye_rev(),
        "sessions": [
            {"id": r["arc"]["id"], "turns": r["arc"]["turns"],
             "replies": [x.text for x in r["replies"]]}
            for r in rows
        ],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    out = REPORTS / f"arcs-{args.provider}-{stamp}.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = [f"# 情绪弧评测（{label}）\n"]
    lines.append(f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}")
    lines.append(f"- 会话数：{summary.get('sessions', 0)}｜总轮数：{summary.get('turns', 0)}")
    lines.append("")

    lines.append("## 汇总\n")
    lines.append("| 指标 | 值 | 方向 |")
    lines.append("|---|---|---|")
    lines.append(f"| 峰值后回落 | {summary.get('peak_relief', 0)}/{summary.get('relief_eligible', 0)}（峰值≥2 的会话）| 越高越好 |")
    lines.append(f"| 卡带率 | {summary.get('stuck_rate', 0):.0%} | 越低越好 |")
    lines.append(f"| 复读率 | {summary.get('repeat_rate', 0):.0%} | 越低越好 |")
    lines.append(f"| 断崖率 | {summary.get('jump_rate', 0):.0%} | 越低越好 |")
    lines.append(f"| 抢跑次数 | {summary.get('lead_count', 0)} | 越低越好 |")
    lines.append(f"| 策略多样性 | {summary.get('diversity', 0):.2f} | 越高越好 |")
    lines.append("")

    lines.append("## 逐段\n")
    lines.append("| 会话 | 轮数 | 峰值 | 结束 | 回落 | 卡带 | 复读 | 断崖 | 提问率 | 多样性 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for row in rows:
        rep = row["report"]
        lines.append(
            f"| {row['arc']['id']} | {rep.turns} | {rep.peak_intensity} | {rep.end_intensity} | "
            f"{'✓' if rep.peak_relief else '✗'} | {rep.stuck_rate:.0%} | {rep.repeat_rate:.0%} | "
            f"{rep.jump_rate:.0%} | {rep.question_rate:.0%} | {rep.diversity:.2f} |"
        )
    lines.append("")

    lines.append("## 对话明细\n")
    for row in rows:
        lines.append(f"### {row['arc']['id']}\n")
        for i, (user_text, reply) in enumerate(zip(row["arc"]["turns"], row["replies"]), 1):
            features = row["features"][i - 1] if i - 1 < len(row["features"]) else None
            tag = (
                f"（{features.strategy}/强度{features.intensity}）" if features else "（失败）"
            )
            lines.append(f"{i}. **用户**：{user_text}")
            lines.append(f"   **助手**{tag}：{reply.text or '⚠️ ' + str(reply.notes)}")
        lines.append("")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_result("arcs", {
        "sessions": summary.get("sessions", 0),
        "turns": summary.get("turns", 0),
        "peak_relief": summary.get("peak_relief", 0),
        "relief_eligible": summary.get("relief_eligible", 0),
        "stuck_rate": round(summary.get("stuck_rate", 0), 3),
        "repeat_rate": round(summary.get("repeat_rate", 0), 3),
        "jump_rate": round(summary.get("jump_rate", 0), 3),
        "lead_count": summary.get("lead_count", 0),
        "diversity": round(summary.get("diversity", 0), 2),
        "question_rate": round(summary.get("question_rate", 0), 3),
        "two_part_rate": round(summary.get("two_part_rate", 0), 3),
        "opener_two_part": summary.get("opener_two_part", 0),
    }, provider=args.provider)
    print(f"原始 -> {run_file.relative_to(ROOT)}")
    print(f"报告 -> {out.relative_to(ROOT)}")
    if summary:
        print(
            f"回落 {summary['peak_relief']}/{summary['relief_eligible']}｜"
            f"卡带 {summary['stuck_rate']:.0%}｜复读 {summary['repeat_rate']:.0%}｜"
            f"断崖 {summary['jump_rate']:.0%}｜多样性 {summary['diversity']:.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
