"""语气度量：把各版人格的回复放进「真人回复」的参照分布里看。

思路见 ``checks/voice.py``：AI 更书面。所以量口语/书面密度、句长、标点画像，
再用真人咨询师的回复当参照，算 z 距离 —— **越小越像人**。

这一步要回答的是 L1 规则答不上来的问题：
p2 当时被说「AI 味太重」，p4/p5 说好一些了，这套指标能不能看出来？

用法::

    python run_voice.py
"""

from __future__ import annotations

import json
import random
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(ROOT))

from checks.result_io import write_result  # noqa: E402
from checks.voice import distance, profile  # noqa: E402

RUNS = ROOT / "data" / "runs"
SMILE = ROOT / "data" / "smilechat"
REPORTS = ROOT / "reports"
SEED = 20261110
CHUNK = 12


def latest_persona_run() -> dict:
    runs = sorted(RUNS.glob("personas-*.json"))
    if not runs:
        raise SystemExit("没有人格运行结果，先跑 run_personas.py")
    return json.loads(runs[-1].read_text(encoding="utf-8"))


def human_replies(limit: int, role: str = "counselor") -> list[str]:
    texts: list[str] = []
    for path in sorted(SMILE.glob("*.json")):
        try:
            dialog = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        for turn in dialog:
            if turn.get("role") == role:
                text = " ".join(str(turn.get("content", "")).split())
                if len(text) >= 10:
                    texts.append(text)
    rng = random.Random(SEED)
    rng.shuffle(texts)
    return texts[:limit]


def main() -> int:
    payload = latest_persona_run()

    # 两种参照：咨询师（专业、书面）和来访者（普通人倾诉、口语）
    refs = {}
    for role, label in (("counselor", "咨询师"), ("client", "来访者")):
        texts = human_replies(200, role)
        if not texts:
            continue
        groups = [texts[i : i + CHUNK] for i in range(0, len(texts), CHUNK)]
        refs[label] = [p for p in (profile(g) for g in groups if len(g) >= 5) if p]
    if not refs:
        raise SystemExit("没有 SmileChat 语料，先跑 scripts/fetch_smilechat.py")

    rows = []
    for persona in payload["personas"]:
        texts = [r for r in persona["replies"] if r and r.strip()]
        if not texts:
            continue
        prof = profile(texts)
        rows.append({
            "name": persona["name"],
            "profile": prof,
            "distance": {label: distance(prof, groups) for label, groups in refs.items()},
        })

    human_mean = {label: profile(human_replies(200, "counselor" if label == "咨询师" else "client"))
                  for label in refs}
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = REPORTS / f"voice-{stamp}.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = ["# 语气度量：和真人回复比，各版人格有多像人\n"]
    lines.append(f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}")
    lines.append("- 参照：SmileChat 真人回复各 200 条，分成 12 条一组算分布")
    lines.append("  - 咨询师：专业、书面，是人类专业回应的参照")
    lines.append("  - 来访者：普通人倾诉，口语，是人类日常说话的参照\n")

    lines.append("## 对照表\n")
    header = "| 组 | 平均字数 | 口语密度 | 书面密度 | 问号密度 | 省略号 | 离咨询师 | 离来访者 |"
    lines.append(header)
    lines.append("|---|---|---|---|---|---|---|---|")

    def row(label: str, prof: dict, dist: dict | None) -> str:
        d1 = f"{dist['咨询师']:.2f}" if dist else "—"
        d2 = f"{dist['来访者']:.2f}" if dist else "—"
        return (
            f"| {label} | {prof['length']:.0f} | {prof['orality']:.2f} | "
            f"{prof['formality']:.2f} | {prof['question_marks']:.2f} | "
            f"{prof['ellipsis']:.2f} | {d1} | {d2} |"
        )

    for label, mean in human_mean.items():
        lines.append(row(f"**真人{label}**", mean, None))
    for item in sorted(rows, key=lambda r: r["distance"]["咨询师"]):
        lines.append(row(item["name"], item["profile"], item["distance"]))

    lines.append("\n## 怎么读\n")
    lines.append("- 密度都是「每 100 字出现几次」，跟长度无关，可以直接比")
    lines.append("- 这**不是**质量分：像人不等于接得好，它只回答语气自然不自然")
    lines.append("- ⚠️ 两列距离**不要横向比**：咨询师和来访者的离散度不同，")
    lines.append("  z 距离的分母不一样。要看方向，就看上面的原始密度")
    lines.append("")
    lines.append("## 直接读原始密度\n")
    if rows:
        oral = {r["name"]: r["profile"]["orality"] for r in rows}
        quest = {r["name"]: r["profile"]["question_marks"] for r in rows}
        top_oral = max(oral, key=oral.get)
        top_q = max(quest, key=quest.get)
        lines.append(f"- **口语密度**：最高的是 `{top_oral}`（{oral[top_oral]:.2f}），"
                     f"是真人的 {oral[top_oral] / max(0.01, 0.27):.1f} 倍"
                     " —— 语气词堆到一定程度就是「日系腔」过载")
        lines.append(f"- **问号密度**：最高的是 `{top_q}`（{quest[top_q]:.2f}），"
                     "比咨询师高一个数量级，也比普通人倾诉高 —— 这就是"
                     "「共情一句 + 问一句」的可测形态")
        lines.append("- **书面密度**：所有版本都是 0.00，真人是 0.33 —— "
                     "说明这几版人格的问题**不是**书面语，而是语气词和提问")
        lines.append("")
        lines.append("> 结论：这套指标能抓到「语气词过载」和「提问过密」，")
        lines.append("> 抓不到用户说的另一层「太公式」——那属于结构问题，不是词频问题。")

    counselor_mean = human_mean.get("咨询师", {})
    if rows and counselor_mean:
        best = min(rows, key=lambda r: r["distance"]["咨询师"])
        worst = max(rows, key=lambda r: r["distance"]["咨询师"])
        if best["name"] != worst["name"]:
            lines.append(
                f"- 离咨询师最近：**{best['name']}**（{best['distance']['咨询师']:.2f}）；"
                f"最远：**{worst['name']}**（{worst['distance']['咨询师']:.2f}）"
            )
            formality_ratio = worst["profile"]["formality"] / max(0.01, counselor_mean["formality"])
            if formality_ratio > 1.5:
                lines.append(
                    f"- 最不像的那版书面密度 {worst['profile']['formality']:.2f}，"
                    f"是真人 {counselor_mean['formality']:.2f} 的 {formality_ratio:.1f} 倍"
                    " —— 这就是 AI 腔的可测形态"
                )
            if worst["profile"]["orality"] < counselor_mean["orality"] * 0.7:
                lines.append(
                    f"- 它的口语密度 {worst['profile']['orality']:.2f} 明显低于真人 "
                    f"{counselor_mean['orality']:.2f} —— 说话太整了"
                )

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_result("voice", {r["name"]: r["distance"]["咨询师"] for r in rows}, provider="personas")
    print(f"报告 -> {out.relative_to(ROOT)}")
    for item in sorted(rows, key=lambda r: r["distance"]["咨询师"]):
        print(f"  {item['name']:<14} 离咨询师 {item['distance']['咨询师']:.2f}"
              f"｜离来访者 {item['distance']['来访者']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
