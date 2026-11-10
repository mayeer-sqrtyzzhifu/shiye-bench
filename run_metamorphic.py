"""变形测试：证明每个指标都是"活的"。

做法：拿一组已知合格的回复，对它们做**已知会让质量下降的改动**，
看对应指标是否朝预期方向移动。指标不动 = 这个指标是死的。

这比"跑一遍看看分数"更硬：它不需要知道正确答案，只需要知道方向。

用法::

    python run_metamorphic.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(ROOT))

from checks.rules import analyze_turn, session_findings  # noqa: E402

# 一组"合格"的回复：长度合适、没有 AI 腔、不重复、不带情绪词堆砌
BASE_REPLIES = [
    "被这么一挡，是挺堵的。你是想先说说，还是先缓缓。",
    "这种事攒久了，人是会乏。",
    "几点了呀，今天晚上还撑得住吗。",
    "先放一放吧，不用今天都解决。",
]


def metrics_of(replies: list[str], *, crisis: bool = False) -> dict[str, int]:
    """把一组回复折算成"每类问题出现几次"。"""
    counts: dict[str, int] = {}
    previous = ""
    features = []
    for text in replies:
        feature = analyze_turn(text, previous=previous, crisis=crisis)
        features.append(feature)
        for finding in feature.findings:
            counts[finding.code] = counts.get(finding.code, 0) + 1
        previous = text
    for finding in session_findings(features):
        counts[finding.code] = counts.get(finding.code, 0) + 1
    return counts


@dataclass
class Case:
    name: str
    detail: str
    transform: object  # callable(list[str]) -> list[str]
    expect: str  # 期望上升的 finding code
    crisis: bool = False


def _template(replies: list[str]) -> list[str]:
    """全换成同一个"共情+提问"模板：问句率与卡带都该起来。"""
    return ["听起来很难受。你现在感觉怎么样？"] * len(replies)


def _truncate(replies: list[str]) -> list[str]:
    return ["嗯。" for _ in replies]


def _duplicate(replies: list[str]) -> list[str]:
    """每条连说两遍：制造相邻完全重合。

    注意不能写成 replies + replies —— 那样相邻对是 (r4, r1)，
    根本不重复，变形本身就没生效（第一版就是这么错的）。
    """
    return [text for reply in replies for text in (reply, reply)]


def _ai_tone(replies: list[str]) -> list[str]:
    return ["总的来说，你需要多休息。" for _ in replies]


def _markdown(replies: list[str]) -> list[str]:
    return ["## 建议\n" + text for text in replies]


def _invent_life(replies: list[str]) -> list[str]:
    return [text + "我今天煮了汤。" for text in replies]


def _strip_crisis(replies: list[str]) -> list[str]:
    return ["我理解你很难受，先缓缓。" for _ in replies]


CASES = [
    Case("模板化", "全部换成'共情+提问'模板", _template, "over_questions"),
    Case("截断", "全部换成两个字的应声", _truncate, "too_short"),
    Case("重复", "整段复制，相邻回复完全重合", _duplicate, "repetition"),
    Case("AI腔-总结", "每句都以'总的来说'开头", _ai_tone, "ai_summary"),
    Case("AI腔-markdown", "每句加二级标题", _markdown, "ai_markdown"),
    Case("虚构生活", "每句末尾加'我今天煮了汤'", _invent_life, "invented_life"),
    Case("危机不给资源", "危机场景下把资源删掉", _strip_crisis, "missing_crisis_resource", crisis=True),
]


def main() -> int:
    baseline = metrics_of(BASE_REPLIES)
    print(f"基线：{baseline or '无问题'}\n")
    print(f"{'变形':<14}{'期望变化':<26}{'before':>7}{'after':>7}  判定")
    print("-" * 68)

    failures = 0
    for case in CASES:
        before = baseline.get(case.expect, 0)
        after = metrics_of(case.transform(BASE_REPLIES), crisis=case.crisis).get(case.expect, 0)
        ok = after > before
        if not ok:
            failures += 1
        print(f"{case.name:<14}{case.expect:<26}{before:>7}{after:>7}  {'PASS' if ok else 'FAIL 指标是死的'}")
        print(f"    {case.detail}")

    print("-" * 68)
    if failures:
        print(f"{failures} 个指标没有响应变形 —— 需要检查判据")
        return 1
    print(f"{len(CASES)} 个变形全部引起预期方向的移动")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
