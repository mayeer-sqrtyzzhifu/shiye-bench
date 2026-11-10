"""已知组校准：同一批用例跑历代人格，看 benchmark 能不能排出已知的好坏。

这是整套判据的地基。如果它把用户明确否掉的版本排得比满意版本还好，
那后面所有"这版进步了"的结论都不作数。

用法::

    python run_personas.py --limit 12
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(ROOT))

from checks.grounding import grounding  # noqa: E402
from checks.rules import analyze_turn, session_findings, two_part_template  # noqa: E402
from runners.shiye_lib import ShiyeRunner  # noqa: E402

CASES = ROOT / "data" / "cases" / "single_turn.jsonl"
PERSONA_DIR = ROOT / "data" / "personas"
MANIFEST = PERSONA_DIR / "manifest.json"
REPORTS = ROOT / "reports"


def load_persona(name: str) -> str:
    path = PERSONA_DIR / f"{name}.py"
    module_name = f"persona_{name}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module.DEFAULT_PERSONA.render()


def load_cases(limit: int) -> list[dict]:
    if not CASES.exists():
        raise SystemExit("先跑 scripts/make_cases.py")
    items = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    return items[:limit]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--personas", default=None, help="逗号分隔，默认全部")
    args = parser.parse_args(argv)

    if not MANIFEST.exists():
        raise SystemExit("先跑 scripts/extract_personas.py")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if args.personas:
        wanted = set(args.personas.split(","))
        manifest = [m for m in manifest if m["name"] in wanted]

    cases = load_cases(args.limit)
    results = []

    for entry in manifest:
        persona_text = load_persona(entry["name"])
        runner = ShiyeRunner(persona_text=persona_text, with_extraction=False)
        features = []
        for index, case in enumerate(cases):
            replies = runner.converse([case["user"]], case_index=index)
            reply = replies[0]
            if reply.ok and reply.text:
                features.append(analyze_turn(reply.text))
        results.append({"entry": entry, "features": features})
        print(f"{entry['name']:<14} 完成 {len(features)} 条")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    runs_dir = ROOT / "data" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"personas-{stamp}.json").write_text(json.dumps({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "cases": [c["user"] for c in cases],
        "personas": [
            {"name": r["entry"]["name"],
             "replies": [f.text for f in r["features"]]}
            for r in results
        ],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    out = REPORTS / f"personas-{stamp}.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = [f"# 已知组校准（{len(cases)} 条单轮用例 × {len(results)} 版人格）\n"]
    lines.append(f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}\n")
    lines.append("## 对照表\n")
    lines.append("| 版本 | 说明 | 平均长度 | 过短 | 过长 | 语气词开头 | 二段式 | 具体性 | 问句率 | 会话级问题 | 问题率 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")

    summary = []
    for row in results:
        entry, features = row["entry"], row["features"]
        n = len(features) or 1
        lengths = [f.length for f in features]
        short = sum(1 for f in features if any(x.code == "too_short" for x in f.findings))
        long_ = sum(1 for f in features if any(x.code == "too_long" for x in f.findings))
        interj = sum(1 for f in features if f.starts_with_interjection)
        two_part = sum(1 for f in features if two_part_template(f.text))
        ground = sum(
            grounding(cases[i]["user"], features[i].text) for i in range(len(features))
        ) / max(1, len(features))
        q_rate = sum(1 for f in features if f.questions > 0) / n
        questions = q_rate
        # 这里比较的是 12 个互不相干的用户开场，不是一段对话，
        # 所以不能套用"对话内提问率"规则（同 run.py）
        session = session_findings(features, same_conversation=False)
        # 按严重度加权；会话级问题**按轮数放大**——
        # "每一句都以语气词开头"是系统性失效，不该和"偶有一句过长"同分。
        turn_score = sum(item.severity for f in features for item in f.findings)
        session_score = sum(item.severity for item in session) * n
        rate = (turn_score + session_score) / n
        summary.append({
            "name": entry["name"],
            "two_part": two_part,
            "note": entry["note"],
            "avg_len": sum(lengths) / len(lengths) if lengths else 0,
            "problem_rate": rate,
        })
        lines.append(
            f"| {entry['name']} | {entry['note']} | "
            f"{sum(lengths)/len(lengths):.1f} | {short} | {long_} | "
            f"{interj}/{n} | {two_part}/{n} | {ground:.1%} | {questions:.2f} | "
            f"{', '.join(x.code for x in session) or '-'} | {rate:.2f} |"
        )

    lines.append("")
    lines.append("## 策略分布\n")
    for row in results:
        dist = Counter(f.strategy for f in row["features"])
        lines.append(f"- **{row['entry']['name']}**：{dict(dist)}")

    lines.append("")
    lines.append("## 问题率排序（越低越好）\n")
    for item in sorted(summary, key=lambda x: x["problem_rate"]):
        lines.append(f"- {item['name']}：{item['problem_rate']:.2f}")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n报告 -> {out.relative_to(ROOT)}")
    for item in sorted(summary, key=lambda x: x["problem_rate"]):
        print(f"  {item['name']:<14} 问题率 {item['problem_rate']:.2f}  长度 {item['avg_len']:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
