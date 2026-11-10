"""同一批数据，三种问法，看哪一个不是「在考学生自己的笔记」。

问题背景：
之前的判据问的是「是否承接情绪（而不是马上给建议）」。
而 shiye 的人设里就写着「少给建议」——这等于拿它自己的规则考它，
分数高是同义反复。

要验证什么：**一个真正测「被接住」的问法，应该也能给真人咨询师高分。**
咨询师的回复以解释和指导为主，但他们是专业人士，用户是真的被接住的。
如果某个问法把咨询师判成 5%，那它量的不是质量，是"风格像不像陪伴者"。

三组数据、三种问法：

* 真回复（shiye）：应当高
* 真人咨询师：**应当也高**（这是判别某个问法是否有效的关键）
* 硬负例模板：应当低

用法::

    python run_judge_questions.py --limit 12
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
from judge.l2 import judge_question  # noqa: E402
from runners.shiye_lib import _ensure_shiye_on_path  # noqa: E402

_ensure_shiye_on_path()
from companion.provider import OpenAICompatProvider  # noqa: E402

RUNS = ROOT / "data" / "runs"
SMILE = ROOT / "data" / "smilechat"
REPORTS = ROOT / "reports"
SEED = 20261110

QUESTIONS = {
    "合规": "承接了用户的情绪（而不是马上给建议、讲道理、或者转移话题）",
    "结果": "让用户读完更愿意继续把话说完",
    "具体": "回应了用户说到的具体内容，而不是给一句通用的安慰",
}

BAD = [
    "辛苦了，早点休息吧，注意身体。",
    "我完全理解你的感受。建议你可以试试写下来，会好很多。",
    "这确实挺难的，不过你已经很棒了，别给自己太大压力。",
    "往好处想，至少你还有家人支持你呀。",
    "嗯嗯，我懂。对了，你吃饭了吗？",
    "这有什么好难过的，大家都这样过来的。",
]


def agent_pairs(limit: int) -> list[dict]:
    runs = sorted(RUNS.glob("real-*.json"))
    if not runs:
        return []
    payload = json.loads(runs[-1].read_text(encoding="utf-8"))
    items = [c for c in payload["cases"] if c.get("ok") and c.get("reply")]
    return [{"user": c["user"], "reply": c["reply"]} for c in items[:limit]]


def human_pairs(limit: int, role: str = "counselor") -> list[dict]:
    pairs: list[dict] = []
    for path in sorted(SMILE.glob("*.json")):
        try:
            dialog = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        for i in range(len(dialog) - 1):
            a, b = dialog[i], dialog[i + 1]
            if a.get("role") != "client" or b.get("role") != role:
                continue
            user = " ".join(str(a.get("content", "")).split())
            reply = " ".join(str(b.get("content", "")).split())
            if len(user) < 8 or len(reply) < 8:
                continue
            pairs.append({"user": user, "reply": reply})
    rng = random.Random(SEED)
    rng.shuffle(pairs)
    return pairs[:limit]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args(argv)

    base = agent_pairs(args.limit)
    groups = {
        "拾夜": base,
        "真人咨询师": human_pairs(args.limit),
        "硬负例": [
            {"user": item["user"], "reply": BAD[i % len(BAD)]}
            for i, item in enumerate(base)
        ],
    }

    provider = OpenAICompatProvider()
    table: dict[str, dict[str, dict]] = {}
    for group, pairs in groups.items():
        if not pairs:
            continue
        table[group] = {}
        for label, question in QUESTIONS.items():
            yes = fails = 0
            for item in pairs:
                verdict = judge_question(provider, question, item["user"], item["reply"])
                if verdict.answer is None:
                    fails += 1
                elif verdict.answer:
                    yes += 1
            total = len(pairs) - fails
            table[group][label] = {"yes": yes, "total": total, "fails": fails}
            rate = yes / total if total else 0
            print(f"{group:<12}{label:<6}{yes}/{total} ({rate:.0%})  失败 {fails}")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = REPORTS / f"judge-questions-{stamp}.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = ["# 三种问法的对照\n"]
    lines.append(f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}")
    lines.append(f"- 每组 {args.limit} 条\n")
    lines.append("| 组 | " + " | ".join(QUESTIONS) + " |")
    lines.append("|---" * (len(QUESTIONS) + 1) + "|")
    for group in table:
        cells = []
        for label in QUESTIONS:
            r = table[group][label]
            rate = r["yes"] / r["total"] if r["total"] else 0
            cells.append(f"{r['yes']}/{r['total']}（{rate:.0%}）")
        lines.append(f"| {group} | " + " | ".join(cells) + " |")

    lines.append("\n## 问法原文\n")
    for label, question in QUESTIONS.items():
        lines.append(f"- **{label}**：这条回复是否{question}？")

    lines.append("\n## 哪个问法站得住\n")
    verdicts = []
    for label in QUESTIONS:
        agent = table.get("拾夜", {}).get(label, {})
        human = table.get("真人咨询师", {}).get(label, {})
        bad = table.get("硬负例", {}).get(label, {})
        if not (agent.get("total") and human.get("total") and bad.get("total")):
            continue
        a = agent["yes"] / agent["total"]
        h = human["yes"] / human["total"]
        b = bad["yes"] / bad["total"]
        ok = b <= 0.2 and h >= 0.4
        verdicts.append((label, a, h, b, ok))
        lines.append(
            f"- **{label}**：拾夜 {a:.0%}｜咨询师 {h:.0%}｜硬负例 {b:.0%} → "
            + ("可用" if ok else "**不可用**")
        )
        if not ok:
            if b > 0.2:
                lines.append("  - 问题：连明显不合适的模板都判成「是」")
            if h < 0.4:
                lines.append("  - 问题：把专业咨询师的回复判成「否」——"
                             "它量的不是质量，是风格像不像")

    lines.append("")
    usable = [v for v in verdicts if v[4]]
    if usable:
        lines.append(f"**可用问法：{'、'.join(v[0] for v in usable)}**")
    else:
        lines.append("**三种问法都不可用。** 这说明「被接住」这一轴暂时没有可靠判据——"
                     "不是一个措辞问题，是方法问题。")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_result("judge_questions", {
        group: {label: table[group][label]["yes"] for label in QUESTIONS if label in table[group]}
        for group in table
    }, provider="real")
    print(f"报告 -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
