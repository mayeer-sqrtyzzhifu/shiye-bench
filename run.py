"""跑一轮评测，输出 markdown 报告。

用法::

    python run.py --provider fake --limit 20        # 零成本，确定性
    python run.py --provider real --limit 20        # 真实模型

报告刻意做成**差分友好**：同样的口径、同样的字段，两版结果可以直接对比。
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

from checks.grounding import grounding  # noqa: E402
from checks.result_io import write_result  # noqa: E402
from checks.rules import analyze_turn, session_findings, two_part_template  # noqa: E402
from runners.shiye_lib import ShiyeRunner, fake_provider  # noqa: E402

CASES = ROOT / "data" / "cases" / "single_turn.jsonl"
REPORTS = ROOT / "reports"

FAKE_REPLIES = [
    "骂人了啊。先坐会儿，别的等会儿再说。",
    "听着是真累。",
    "嗯。那我不问了，有事喊我。",
    "这事确实磨人。",
    "几点开始的呀。",
]


def load_cases(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"用例文件不存在：{path}（先跑 scripts/make_cases.py）")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_runner(kind: str) -> ShiyeRunner:
    if kind == "fake":
        return ShiyeRunner(provider=fake_provider(FAKE_REPLIES))
    return ShiyeRunner()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("fake", "real"), default="fake")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--cases", default=str(CASES))
    parser.add_argument("--out", default=None)
    parser.add_argument(
        "--samples", type=int, default=1,
        help="每条用例生成几次。>1 时按用例取比例，方差分解见报告",
    )
    args = parser.parse_args(argv)

    cases = load_cases(Path(args.cases))[: args.limit]
    runner = build_runner(args.provider)

    rows = []
    for index, case in enumerate(cases):
        draws = []
        for sample in range(max(1, args.samples)):
            # 每次采样都用全新的库，保证是独立的一次生成
            fresh = build_runner(args.provider)
            replies = fresh.converse([case["user"]], case_index=index)
            draw = replies[0]
            if draw.ok and draw.text:
                draws.append(draw)
        reply = draws[0] if draws else runner.converse([case["user"]], case_index=index)[0]
        features = analyze_turn(reply.text) if reply.ok and reply.text else None
        per_sample = [analyze_turn(d.text) for d in draws]
        rows.append({"case": case, "reply": reply, "features": features,
                     "draws": per_sample})

    # ── 汇总
    ok_rows = [r for r in rows if r["features"]]
    lengths = [r["features"].length for r in ok_rows]
    questions = [r["features"].questions for r in ok_rows]
    strategy = Counter(r["features"].strategy for r in ok_rows)
    intensity = Counter(r["features"].intensity for r in ok_rows)
    finding_codes = Counter(f.code for r in ok_rows for f in r["features"].findings)
    # 会话级规则（问句率 / 语气词开头率）以前只在人格对比脚本里跑，
    # 单轮汇总漏了 —— 而"问句太多"恰恰是最常触发的一条
    for item in session_findings([r["features"] for r in ok_rows], same_conversation=False):
        finding_codes[item.code] += 1
    interjection = sum(1 for r in ok_rows if r["features"].starts_with_interjection)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    # 原始结果落盘：改规则时用 reanalyze.py 重算，不必再花一次模型调用
    runs_dir = ROOT / "data" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_file = runs_dir / f"{args.provider}-{stamp}.json"
    run_file.write_text(json.dumps({
        "provider": args.provider,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "cases": [
            {"id": r["case"]["id"], "user": r["case"]["user"],
             "reply": r["reply"].text, "ok": r["reply"].ok, "notes": r["reply"].notes}
            for r in rows
        ],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    out_path = Path(args.out) if args.out else REPORTS / f"report-{args.provider}-{stamp}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append(f"# 单轮评测报告（{args.provider}）\n")
    lines.append(f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}")
    lines.append(f"- 用例数：{len(cases)}")
    lines.append(f"- 成功回复：{len(ok_rows)}")
    lines.append(f"- 模型：{args.provider}")
    lines.append("")

    lines.append("## 汇总\n")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 平均长度 | {sum(lengths) / len(lengths):.1f} 字 |" if lengths else "| 平均长度 | - |")
    lines.append(f"| 平均问句 | {sum(questions) / len(questions):.2f} |" if questions else "| 平均问句 | - |")
    lines.append(f"| 以语气词开头 | {interjection}/{len(ok_rows)} |" if ok_rows else "| 以语气词开头 | - |")
    lines.append(f"| 策略分布 | {dict(strategy)} |")
    lines.append(f"| 强度分布 | {dict(intensity)} |")
    lines.append(f"| 规则命中 | {dict(finding_codes) or '无'} |")
    lines.append("")

    lines.append("## 逐条\n")
    lines.append("| # | 用户 | 回复 | 长度 | 问句 | 策略 | 规则命中 |")
    lines.append("|---|---|---|---|---|---|---|")
    for row in rows:
        case = row["case"]
        reply = row["reply"]
        features = row["features"]
        user_text = case["user"].replace("|", "｜")
        if features:
            reply_text = features.text.replace("|", "｜").replace("\n", " ")
            codes = ", ".join(f.code for f in features.findings) or "-"
            lines.append(
                f"| {case['id']} | {user_text} | {reply_text} | {features.length} | "
                f"{features.questions} | {features.strategy} | {codes} |"
            )
        else:
            error = reply.notes.get("error", "empty")
            lines.append(f"| {case['id']} | {user_text} | ⚠️ {error} | - | - | - | - |")
    lines.append("")

    if args.samples > 1:
        from checks.variance import decompose

        drawn = [r["draws"] for r in rows if len(r.get("draws", [])) >= 2]
        if drawn:
            lines.append("")
            lines.append("## 方差分解\n")
            lines.append("> 每条用例采样多次，可以把总方差拆成「用例之间」和「用例之内」。"
                         "后者靠多采样能压掉，前者不能。\n")
            for name, flagger in (
                ("二段式", lambda f: two_part_template(f.text)),
                ("带问句", lambda f: f.strategy == "提问"),
            ):
                series = [[bool(flagger(f)) for f in d] for d in drawn]
                dec = decompose(series)
                lines.append(
                    f"- **{name}**：每条采 {dec.samples} 次｜用例间方差 {dec.case_variance:.3f}"
                    f"｜用例内方差 {dec.within:.3f}"
                )
                lines.append(
                    f"  - 可测下限：k=1 约 {dec.floor(1):.0%}；k={dec.samples} 约 "
                    f"{dec.floor(dec.samples):.0%}（降到原来的 {dec.relative_gain(dec.samples):.0%}）"
                )

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_result("single", {
        "grounding": round(
            sum(
                grounding(r["case"]["user"], getattr(r["reply"], "text", "") or "")
                for r in ok_rows
            )
            / max(1, len(ok_rows)), 4
        ),
        "two_part": sum(
            1 for r in ok_rows if two_part_template(getattr(r["reply"], "text", r["reply"]) or "")
        ),
        "cases": len(ok_rows),
        "avg_length": round(sum(lengths) / len(lengths), 1) if lengths else 0,
        "avg_questions": round(sum(questions) / len(questions), 2) if questions else 0,
        "interjection_openings": interjection,
        "finding_count": sum(finding_codes.values()),
    }, provider=args.provider)
    print(f"原始 -> {run_file.relative_to(ROOT)}")
    print(f"报告 -> {out_path.relative_to(ROOT)}")
    if ok_rows:
        print(f"平均长度 {sum(lengths)/len(lengths):.1f}｜问句 {sum(questions)/len(questions):.2f}"
              f"｜语气词开头 {interjection}/{len(ok_rows)}｜规则命中 {sum(finding_codes.values())} 次")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
