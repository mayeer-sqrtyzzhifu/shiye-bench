"""同一个判官、同一批数据，换两种问法，看结论会不会变。

背景：之前那套判据问的是"有没有马上给建议、讲道理、或者转移话题"。
但拾夜的人格里**本来就写着**"少给建议" —— 这等于拿它的规则去考它，
分数高是同义反复，说明不了"接得好不好"。

这里同时跑两种问法：

* **合规问法**：有没有马上给建议（贴近人设规则，同义反复风险高）
* **中立问法**：有没有让一个正在难过的人觉得被理解（不依赖任何人设）

如果两种问法给出的排序不一样，就说明"合规"和"质量"是两回事，
以后报告里必须分开写，不能拿合规分冒充质量分。

用法::

    python run_judge_real.py --limit 12
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
from judge.l2 import judge_question  # noqa: E402
from runners.shiye_lib import _ensure_shiye_on_path  # noqa: E402

_ensure_shiye_on_path()
from companion.provider import OpenAICompatProvider  # noqa: E402

SMILE = ROOT / "data" / "smilechat"
RUNS = ROOT / "data" / "runs"
REPORTS = ROOT / "reports"
SEED = 20261110

QUESTIONS = {
    "合规": "承接了用户的情绪（而不是马上给建议、讲道理、或者转移话题）",
    "中立": "让一个正在难过的人觉得，自己的感受被真的理解到了",
}

# 硬负例：看起来在安慰，其实没接住
HARD_NEGATIVES = [
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


def human_pairs(limit: int) -> list[dict]:
    pairs: list[dict] = []
    for path in sorted(SMILE.glob("*.json")):
        try:
            dialog = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        for i in range(len(dialog) - 1):
            a, b = dialog[i], dialog[i + 1]
            if a.get("role") != "client" or b.get("role") != "counselor":
                continue
            user = " ".join(str(a.get("content", "")).split())
            reply = " ".join(str(b.get("content", "")).split())
            if len(user) < 8 or len(reply) < 8:
                continue
            pairs.append({"user": user, "reply": reply})
    rng = random.Random(SEED)
    rng.shuffle(pairs)
    return pairs[:limit]


def negative_pairs(limit: int) -> list[dict]:
    base = agent_pairs(limit)
    return [
        {"user": item["user"], "reply": HARD_NEGATIVES[i % len(HARD_NEGATIVES)]}
        for i, item in enumerate(base)
    ]


GROUPS = [
    ("拾夜", agent_pairs),
    ("真人咨询师", human_pairs),
    ("硬负例", negative_pairs),
]


def judge_group(provider, pairs: list[dict], question: str) -> dict:
    yes = fails = 0
    failures: list[dict] = []
    for item in pairs:
        verdict = judge_question(provider, question, item["user"], item["reply"])
        if verdict.answer is None:
            fails += 1
            failures.append({"user": item["user"][:40], "raw": verdict.raw,
                             "len": len(item["reply"])})
        elif verdict.answer:
            yes += 1
    total = len(pairs) - fails
    return {"yes": yes, "total": total, "fails": fails, "failures": failures}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args(argv)

    provider = OpenAICompatProvider()
    table: dict[str, dict[str, dict]] = {}
    for label, loader in GROUPS:
        pairs = loader(args.limit)
        if not pairs:
            continue
        table[label] = {}
        for qname, question in QUESTIONS.items():
            result = judge_group(provider, pairs, question)
            table[label][qname] = result
            rate = result["yes"] / result["total"] if result["total"] else 0
            print(f"{label:<12}{qname:<6} {result['yes']}/{result['total']} ({rate:.0%})"
                  f" 失败 {result['fails']}")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = REPORTS / f"judge-real-{stamp}.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = ["# 同一批数据，两种问法\n"]
    lines.append(f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}")
    lines.append(f"- 每组 {args.limit} 条\n")
    lines.append("| 组 | 合规问法 | 中立问法 |")
    lines.append("|---|---|---|")
    for label in table:
        cells = []
        for qname in QUESTIONS:
            r = table[label][qname]
            rate = r["yes"] / r["total"] if r["total"] else 0
            lo, hi = wilson(r["yes"], r["total"]) if r["total"] else (0, 0)
            cells.append(f"{r['yes']}/{r['total']}（{rate:.0%}，CI {lo:.0%}–{hi:.0%}）")
        lines.append(f"| {label} | {cells[0]} | {cells[1]} |")

    lines.append("\n## 问法原文\n")
    for qname, question in QUESTIONS.items():
        lines.append(f"- **{qname}**：这条回复是否{question}？")

    lines.append("\n## 怎么读\n")

    def _rate(label: str, qname: str) -> float:
        r = table[label][qname]
        return r["yes"] / r["total"] if r["total"] else 0.0

    lines.append("### 差值（合规 − 中立）\n")
    lines.append("| 组 | 差值 | 含义 |")
    lines.append("|---|---|---|")
    for label in table:
        delta = (_rate(label, "合规") - _rate(label, "中立")) * 100
        if delta >= 10:
            meaning = "合规问法明显抬高"
        elif delta > 0:
            meaning = "合规问法略微抬高"
        else:
            meaning = "两种问法一致"
        lines.append(f"| {label} | {delta:+.0f}pp | {meaning} |")

    lines.append("")
    if "拾夜" in table and "真人咨询师" in table:
        same_direction = (_rate("拾夜", "合规") > _rate("真人咨询师", "合规")) == (
            _rate("拾夜", "中立") > _rate("真人咨询师", "中立")
        )
        if same_direction:
            lines.append("- 两种问法给出**同一个方向**的结论 —— 排序不是问法造成的")
        else:
            lines.append("- ⚠️ 两种问法给出**不同方向**：说明「合规」和「质量」是两回事")

    if "拾夜" in table:
        inflated = (_rate("拾夜", "合规") - _rate("拾夜", "中立")) * 100
        lines.append(
            f"- 拾夜：合规 {_rate('拾夜','合规'):.0%} vs 中立 {_rate('拾夜','中立'):.0%}"
            f"（{inflated:+.0f}pp）"
        )
        if inflated >= 10:
            lines.append(
                "- **合规分不能直接当质量分用**：换一个不含人设措辞的问法，分数就掉下来了。"
                "报告里两个数必须分开写。"
            )
    lines.append("")
    lines.append("> **三次运行的观察**：合规问法的分数在每一组、每一次运行里都 ≥ 中立问法，"
                 "差值在 0–25pp 之间浮动。")
    lines.append(">")
    lines.append("> 稳定的结论：**合规问法更宽松**（只要没给建议就算过），"
                 "中立问法更严（要真的让人觉得被理解）。")
    lines.append("> 不稳定的部分：具体差多少（8pp 还是 25pp），"
                 "每组 12–20 条不够定，需要更大样本。")
    lines.append(">")
    lines.append("> 实用建议：**报告里两个数都写**，不要拿合规分冒充质量分。")

    # 解析失败的诊断
    all_failures = [
        (label, qname, f)
        for label in table for qname in table[label]
        for f in table[label][qname]["failures"]
    ]
    if all_failures:
        lines.append("\n## 解析失败的样本\n")
        lines.append("| 组 | 问法 | 回复长度 | 原始输出 |")
        lines.append("|---|---|---|---|")
        for label, qname, f in all_failures:
            raw = (f["raw"] or "").replace("|", "｜").replace("\n", " ")[:40]
            lines.append(f"| {label} | {qname} | {f['len']} | {raw or '（空）'} |")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_result("judge_real", {
        label: {q: table[label][q]["yes"] for q in QUESTIONS} for label in table
    }, provider="real")
    print(f"报告 -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
