"""用（经过验证的）判据去给历代人格打分，看排序对不对得上用户的判断。

上一轮把问法换掉了：从「是否承接情绪（而不是马上给建议）」换成
「是否回应了用户说到的具体内容」。后者不含任何人设措辞，
对真人咨询师也能给出合理分数（58% vs 旧问法的 27%）。

现在的问题是：**它能不能排出用户已知的好恶？**
用户当时的顺序是 p1/p2 不行（太 AI）、p3 太公式、p4 好转、p5 满意。

用法::

    python run_judge_personas.py --limit 12
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(ROOT))

from checks.result_io import wilson, write_result  # noqa: E402
from judge.l2 import NEED_QUESTIONS, judge_need  # noqa: E402
from runners.shiye_lib import _ensure_shiye_on_path  # noqa: E402

_ensure_shiye_on_path()
from companion.provider import OpenAICompatProvider  # noqa: E402

RUNS = ROOT / "data" / "runs"
REPORTS = ROOT / "reports"
NEED = "被接住"


def latest_persona_run() -> dict:
    runs = sorted(RUNS.glob("personas-*.json"))
    if not runs:
        raise SystemExit("没有人格运行结果，先跑 run_personas.py")
    # 取覆盖最多人格版本的那一个
    best = None
    for path in runs:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if best is None or len(payload["personas"]) > len(best[1]["personas"]):
            best = (path, payload)
    return best[1] if best else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args(argv)

    payload = latest_persona_run()
    cases = payload["cases"]
    provider = OpenAICompatProvider()

    rows = []
    for persona in payload["personas"]:
        replies = persona["replies"][: args.limit]
        yes = fails = 0
        for user, reply in zip(cases, replies):
            if not (reply or "").strip():
                continue
            verdict = judge_need(provider, user, reply, NEED)
            if verdict.answer is None:
                fails += 1
            elif verdict.answer:
                yes += 1
        total = sum(1 for r in replies if (r or "").strip()) - fails
        rows.append({"name": persona["name"], "yes": yes, "total": total, "fails": fails})
        print(f"{persona['name']:<14} {yes}/{total}")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = REPORTS / f"judge-personas-{stamp}.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = ["# 判据给历代人格打分\n"]
    lines.append(f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}")
    lines.append(f"- 问题：这条回复是否{NEED_QUESTIONS[NEED]}？")
    lines.append(f"- 每种人格 {args.limit} 条开场用例\n")
    lines.append("| 版本 | 判「是」 | 比例 | 95% CI |")
    lines.append("|---|---|---|---|")
    for row in rows:
        if not row["total"]:
            lines.append(f"| {row['name']} | - | - | - |")
            continue
        lo, hi = wilson(row["yes"], row["total"])
        lines.append(
            f"| {row['name']} | {row['yes']}/{row['total']} | "
            f"{row['yes'] / row['total']:.0%} | {lo:.0%}–{hi:.0%} |"
        )

    lines.append("\n## 能不能排出来\n")
    ordered = sorted([r for r in rows if r["total"]], key=lambda r: r["yes"] / r["total"])
    if ordered:
        lines.append("从低到高：")
        for row in ordered:
            lines.append(f"- {row['name']}：{row['yes'] / row['total']:.0%}")
        lines.append("")
        lines.append("用户当时的判断是：p1/p2 不行（AI 味）、p3 太公式、p4 好转、p5 满意。")
        spread = (ordered[-1]["yes"] - ordered[0]["yes"]) / max(1, ordered[0]["total"])
        lines.append(f"\n极差 {spread:.0%}。")
        if spread < 0.2:
            lines.append("**极差太小，这套判据排不出人格差异。**")
        else:
            lines.append("极差够大，但顺序是否与用户判断一致，要人来看上表。")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_result("judge_personas", {r["name"]: r["yes"] for r in rows}, provider="real")
    print(f"报告 -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
