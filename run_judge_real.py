"""用**真实人类回复**当对照，测判官的假阳性率。

前几轮判官的"是"率一直是 100%（12/12 真实回复），这本身可疑：
如果一个判官对什么都点头，它在真实数据上的结论就没有信息量。

对照组是 SmileChat 里**真人咨询师的回复**。它们是真实的人写的，
而且是"给建议为主"的风格（PsyQA 统计里解释+指导占 81%），
正好可以检验判官会不会把"给建议"判成"没接住"。

三种分布放在一起看，判官有没有分辨力就一目了然：

* 拾夜的回复（应当高）
* 真人咨询师的回复（应当中）
* 硬负例模板（应当低）

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

from checks.result_io import write_result  # noqa: E402
from judge.l2 import judge_need  # noqa: E402
from runners.shiye_lib import _ensure_shiye_on_path  # noqa: E402

_ensure_shiye_on_path()
from companion.provider import OpenAICompatProvider  # noqa: E402

SMILE = ROOT / "data" / "smilechat"
RUNS = ROOT / "data" / "runs"
REPORTS = ROOT / "reports"
SEED = 20261110
NEED = "被接住"


def human_pairs(limit: int) -> list[dict]:
    """从 SmileChat 抽 (来访者, 咨询师回复) 对。"""
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


def agent_pairs(limit: int) -> list[dict]:
    runs = sorted(RUNS.glob("real-*.json"))
    if not runs:
        return []
    payload = json.loads(runs[-1].read_text(encoding="utf-8"))
    items = [c for c in payload["cases"] if c.get("ok") and c.get("reply")]
    return [{"user": c["user"], "reply": c["reply"]} for c in items[:limit]]


def judge_batch(provider, pairs: list[dict], label: str) -> dict:
    yes = 0
    fails = 0
    for item in pairs:
        verdict = judge_need(provider, item["user"], item["reply"], NEED)
        if verdict.answer is None:
            fails += 1
        elif verdict.answer:
            yes += 1
    total = len(pairs) - fails
    print(f"{label:<16} 判'是' {yes}/{total}（失败 {fails}）")
    return {"label": label, "yes": yes, "total": total, "fails": fails}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args(argv)

    provider = OpenAICompatProvider()
    groups = [
        judge_batch(provider, agent_pairs(args.limit), "拾夜"),
        judge_batch(provider, human_pairs(args.limit), "真人咨询师"),
    ]

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = REPORTS / f"judge-real-{stamp}.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = ["# 判官在真实回复上的分布\n"]
    lines.append(f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}")
    lines.append(f"- 问题：这条回复有没有接住用户的情绪（{NEED}）？（{args.limit} 条/组）\n")
    lines.append("| 组 | 判'是' | 比例 |")
    lines.append("|---|---|---|")
    for g in groups:
        rate = g["yes"] / g["total"] if g["total"] else 0
        lines.append(f"| {g['label']} | {g['yes']}/{g['total']} | {rate:.0%} |")

    lines.append("\n## 怎么读这张表\n")
    agent = groups[0]
    human = groups[1]
    if agent["total"] == 0:
        lines.append("- 没有拾夜的运行结果，先跑 run.py --provider real")
    elif human["total"] == 0:
        lines.append("- 没有 SmileChat 数据，先跑 scripts/fetch_smilechat.py")
    elif human["yes"] == human["total"] and agent["yes"] == agent["total"]:
        lines.append("- ⚠️ 两组都是 100% —— 判官在这次对比里没有分辨力，"
                     "它给出的'接住率'不能当结论")
    else:
        lines.append(f"- 拾夜 {agent['yes']}/{agent['total']}，真人咨询师 {human['yes']}/{human['total']}")
        if agent["yes"] > human["yes"]:
            lines.append("- 拾夜判'接住'的比例高于真人咨询师。"
                         "合理：咨询师的回复以解释和指导为主（PsyQA 统计占 81%），"
                         "而拾夜的人格要求少给建议。")
            lines.append("")
            lines.append("## ⚠️ 这张表不能直接读成\"拾夜比真人咨询师更会接住\"")
            lines.append("")
            lines.append("三个混淆因素：")
            lines.append("")
            lines.append("1. **判据的措辞和人设同源**。判据问的是\"是否没马上给建议\"，"
                         "而拾夜的人格里就写着\"少给建议\"。这是**同义反复**：")
            lines.append("   量的是\"有没有遵守自己的人格\"，不是\"接得好不好\"。")
            lines.append("2. **职业不同**。咨询师的工作本来就是给解释和指导，"
                         "用\"陪伴\"的标准去判他们，判低是必然的。")
            lines.append("3. **判官与被测模型同家族**（都是 deepseek），同族偏爱无法排除。")
            lines.append("")
            lines.append("所以这张表能说明的是：**判官不是只会点头**（分布确实分开了），"
                         "以及**拾夜的行为和它自己的人设一致**。")
            lines.append("它不能说明的是：拾夜比人类更会陪伴。")
        elif agent["yes"] == human["yes"]:
            lines.append("- 两组比例相同 —— 判官能区分的是'明显没接住'，"
                         "分不出这两个群体。")
        else:
            lines.append("- 拾夜低于真人咨询师 —— 需要看具体样本，可能是过度提问或过早给建议。")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_result("judge_real", {g["label"]: {"yes": g["yes"], "total": g["total"]} for g in groups},
                 provider="real")
    print(f"报告 -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
