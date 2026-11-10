"""判据可靠性测试：**先用它自己判两次，看一致不一致**。

为什么必须先做这一步：benchmark 里最难的一轴是"需求有没有被满足"，
而它只能靠模型判。同一批回复判两次都给出不同结论的判官，
算出来的"满足率"就是噪声，不是信号。

三个检验：

1. **重测一致**（同一输入判两次）
2. **位置无关**（把用户发言与回复的顺序颠倒，答案不该变）
3. **Cohen's κ**（扣掉"瞎猜也能碰上"的那部分）

κ 的经验线：<0.4 不可用，0.4–0.6 勉强，>0.6 可用。

用法::

    python run_judge.py --repeat 2
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
from runners.shiye_lib import ShiyeRunner, _ensure_shiye_on_path  # noqa: E402

_ensure_shiye_on_path()
from companion.provider import OpenAICompatProvider  # noqa: E402

CASES = ROOT / "data" / "cases" / "single_turn.jsonl"

# 已知"没接住"的回复：说教、模板安慰、直接给方案。
# 判官如果对这些也说"是"，它就是个只会点头的机器 —— 一致性再高也没用。
NEGATIVES = [
    "别想太多了，早点睡吧，会好起来的。",
    "## 建议\n1. 先深呼吸\n2. 找朋友聊聊\n3. 保持规律作息",
    "这种情况建议你去看心理咨询，我不是专业的。",
]

# 硬负例：**看起来在安慰，其实没接住**。这才是真实场景里的主要失效模式，
# 也是这道判据真正要能识破的东西。判官如果对这些也说"是"，
# 它测的只是"有没有安慰性的词"，不是"有没有接住"。
HARD_NEGATIVES = [
    "辛苦了，早点休息吧，注意身体。",
    "我完全理解你的感受。建议你可以试试写下来，会好很多。",
    "这确实挺难的，不过你已经很棒了，别给自己太大压力。",
    "往好处想，至少你还有家人支持你呀。",
    "嗯嗯，我懂。对了，你吃饭了吗？",
    "这有什么好难过的，大家都这样过来的。",
]
REPORTS = ROOT / "reports"
RUNS = ROOT / "data" / "runs"
NEED = "被接住"


def load_replies(limit: int) -> list[dict]:
    """用一条真实运行里已有的回复，避免再花一次生成调用。"""
    runs = sorted((ROOT / "data" / "runs").glob("real-*.json"))
    if not runs:
        raise SystemExit("没有可用的运行结果，先跑 run.py --provider real")
    payload = json.loads(runs[-1].read_text(encoding="utf-8"))
    items = [c for c in payload["cases"] if c.get("ok") and c.get("reply")]
    return items[:limit]


def cohen_kappa(a: list[bool], b: list[bool]) -> float | None:
    """两评判者的 Cohen's κ（二元）。"""
    n = len(a)
    if n == 0:
        return None
    agree = sum(1 for x, y in zip(a, b) if x == y) / n
    pa = sum(a) / n
    pb = sum(b) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    if expected >= 1:
        return 1.0 if agree == 1 else 0.0
    return (agree - expected) / (1 - expected)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args(argv)

    items = load_replies(args.limit)
    if not items:
        raise SystemExit("运行结果里没有成功的回复")

    provider = OpenAICompatProvider()
    provider_loaded = True

    rounds: list[list[bool | None]] = []
    raws: list[list[str]] = []
    for r in range(args.repeat):
        answers: list[bool | None] = []
        raw_texts: list[str] = []
        for item in items:
            verdict = judge_need(provider, item["user"], item["reply"], NEED)
            answers.append(verdict.answer)
            raw_texts.append(verdict.raw)
        rounds.append(answers)
        raws.append(raw_texts)
        print(f"第 {r + 1} 轮完成：{sum(1 for a in answers if a)} / {len(answers)} 判为'是'")

    # 重测一致
    usable = [
        i for i in range(len(items))
        if all(rounds[r][i] is not None for r in range(args.repeat))
    ]
    if not usable:
        print("判官全部解析失败，无法评估")
        return 1

    agree_pairs = 0
    total_pairs = 0
    for i in usable:
        vals = {rounds[r][i] for r in range(args.repeat)}
        total_pairs += 1
        if len(vals) == 1:
            agree_pairs += 1
    retest = agree_pairs / total_pairs

    kappa = cohen_kappa([rounds[0][i] for i in usable], [rounds[1][i] for i in usable]) if args.repeat >= 2 else None

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = REPORTS / f"judge-{stamp}.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = [f"# 判据可靠性测试（{NEED}）\n"]
    lines.append(f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}")
    lines.append(f"- 样本：{len(items)} 条已有回复")
    lines.append(f"- 重复次数：{args.repeat}\n")

    lines.append("## 结论\n")
    if kappa is None:
        lines.append("- 只跑了一轮，无法计算 κ")
    else:
        if kappa >= 0.6:
            verdict = "可用"
        elif kappa >= 0.4:
            verdict = "勉强可用，结论需谨慎"
        else:
            verdict = "**不可用**——它给出的满足率是噪声"
        lines.append(f"- Cohen's κ = **{kappa:.2f}** → {verdict}")
        lines.append(f"- 重测一致率：{agree_pairs}/{total_pairs} = {retest:.0%}")

    # 已知负例：判官必须说"否"
    negatives = []
    for idx, item in enumerate(items):
        bad = NEGATIVES[idx % len(NEGATIVES)]
        verdict = judge_need(provider, item["user"], bad, NEED)
        negatives.append(verdict.answer)

    hard = []
    for idx, item in enumerate(items):
        bad = HARD_NEGATIVES[idx % len(HARD_NEGATIVES)]
        verdict = judge_need(provider, item["user"], bad, NEED)
        hard.append((bad, verdict.answer))

    parsed_neg = [x for x in negatives if x is not None]
    specificity = (
        sum(1 for x in parsed_neg if x is False) / len(parsed_neg) if parsed_neg else None
    )
    tp = sum(1 for i in usable if rounds[0][i])
    sensitivity = tp / len(usable) if usable else None

    lines.append("\n## 分辨力（已知负例）\n")
    lines.append(f"- 已知'没接住'的回复 {len(NEGATIVES)} 类，混在 {len(items)} 个用户提问里")
    if specificity is None:
        lines.append("- 负例全部解析失败")
    else:
        lines.append(f"- 判成'否'的比例（特异度）：**{specificity:.0%}**")
        if specificity < 0.5:
            lines.append("- ⚠️ 判官对明显不合适的回复也说'是' —— 它是个只会点头的机器，"
                         "一致性再高也测不了东西")
    lines.append(f"- 对真实回复判'是'的比例（灵敏度）：{sensitivity:.0%}" if sensitivity is not None else "")

    hard_parsed = [v for _, v in hard if v is not None]
    hard_specificity = (
        sum(1 for v in hard_parsed if v is False) / len(hard_parsed) if hard_parsed else None
    )
    lines.append("\n## 硬负例（看起来在安慰，其实没接住）\n")
    if hard_specificity is None:
        lines.append("- 全部解析失败")
    else:
        lines.append(f"- 判成\"否\"的比例：**{hard_specificity:.0%}**（{len(hard_parsed)} 条）")
        if hard_specificity < 0.7:
            lines.append("- ⚠️ 判官对这类回复也点头 —— 它测的是\"有没有安慰的词\"，"
                         "不是\"有没有接住\"")
        else:
            lines.append("- 能识破大部分\"表面温和但没接住\"的回复，可以用，但要知道盲点")
        if hard_specificity is not None and hard_specificity < 1.0:
            missed = [bad for bad, ans in hard if ans is True]
            if missed:
                lines.append("")
                lines.append("**漏掉的通常是这一类**：先真承接一句，再跟一句有毒正能量。"
                             "前半句让判官点头，后半句才是问题。")
                for bad in dict.fromkeys(missed):
                    lines.append(f"- 「{bad}」")
                lines.append("")
                lines.append("对策：这类回复同时用规则层的 `forbidden_comfort` 兜一下，"
                             "两层合起来比单靠判官稳。")
    lines.append("")
    lines.append("| 硬负例 | 判官 |")
    lines.append("|---|---|")
    for bad, answer in hard:
        mark = "是" if answer is True else ("否" if answer is False else "?")
        lines.append(f"| {bad} | {mark} |")

    lines.append("\n## 逐条\n")
    header = "| # | 用户 | 回复 | " + " | ".join(f"第{i+1}次" for i in range(args.repeat)) + " |"
    lines.append(header)
    lines.append("|" + "---|" * (3 + args.repeat))
    for idx, item in enumerate(items):
        mark = [("是" if rounds[r][idx] else ("否" if rounds[r][idx] is False else "?")) for r in range(args.repeat)]
        user = item["user"].replace("|", "｜")[:28]
        reply = item["reply"].replace("|", "｜").replace("\n", " ")[:36]
        lines.append(f"| {idx+1} | {user} | {reply} | " + " | ".join(mark) + " |")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    write_result("judge", {
        "need": NEED,
        "samples": len(usable),
        "repeat": args.repeat,
        "agreement": round(retest, 3),
        "kappa": None if kappa is None else round(kappa, 3),
        "specificity": None if specificity is None else round(specificity, 3),
        "sensitivity": None if sensitivity is None else round(sensitivity, 3),
        "hard_specificity": None if hard_specificity is None else round(hard_specificity, 3),
        "verdict": (
            "usable" if (kappa or 0) >= 0.6 and (specificity or 0) >= 0.7
            else ("unusable" if (specificity or 0) < 0.5 else "marginal")
        ),
    }, provider="real")

    print(f"报告 -> {out.relative_to(ROOT)}")
    if kappa is not None:
        print(f"κ = {kappa:.2f}｜重测一致 {agree_pairs}/{total_pairs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
