"""轨迹指标：一段对话里，情绪是怎么走的。

单轮指标只能看"这一句回得好不好"，看不了"整条线有没有走"。这里补上后者的
可计算部分——全部基于 ``checks.rules`` 的规则标注，不调用模型。

六个指标：

* ``peak_relief``  峰值后 3 轮内强度是否下降 ≥1 档（一直顶在峰上 = 没走）
* ``jump_rate``    |Δagent| ≥2 而 |Δuser| ≤1 的轮次占比（断崖）
* ``stuck_rate``   连续 3 轮同策略 + 同强度（卡带）
* ``repeat_rate``  相邻回复 4-gram 重合 >0.4（复读）
* ``lead_complaint`` agent 强度领先 user 超过 1 档的轮次（抢跑）
* ``diversity``    不同策略数 / 轮数（越低越像模板）

这些指标的价值在于**方向明确**：下降就是不好，不需要人来判"几分算好"。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .rules import TurnFeatures, check_repetition


@dataclass
class ArcReport:
    turns: int
    peak_turn: int | None
    peak_intensity: int
    end_intensity: int
    peak_relief: bool
    relief_eligible: bool  # 峰值 <2 时无法判断回落，不计入分母
    jump_rate: float
    stuck_rate: float
    repeat_rate: float
    lead_count: int
    diversity: float
    question_rate: float = 0.0
    two_part_rate: float = 0.0
    opener_two_part: bool = False
    findings: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        return (
            f"轮数 {self.turns}｜峰值 {self.peak_intensity}（第 {self.peak_turn} 轮）"
            f"→ 结束 {self.end_intensity}｜回落 {'✓' if self.peak_relief else '✗'}｜"
            f"卡带 {self.stuck_rate:.0%}｜复读 {self.repeat_rate:.0%}｜"
            f"断崖 {self.jump_rate:.0%}｜抢跑 {self.lead_count}｜多样性 {self.diversity:.2f}"
        )


def _delta(values: list[int], index: int) -> int:
    if index == 0:
        return 0
    return values[index] - values[index - 1]


def analyze_arc(
    agent: list[TurnFeatures],
    user_intensity: list[int],
) -> ArcReport:
    """agent 是每轮回复的特征；user_intensity 是每轮用户发言的强度。"""
    n = len(agent)
    if n == 0:
        return ArcReport(0, None, 0, 0, True, False, 0.0, 0.0, 0.0, 0, 0.0)

    # 提问率：人格写着"问句至多一半"，多个轮次连着问就是公式化
    question_rate = sum(1 for f in agent if f.strategy == "提问") / n
    from checks.rules import two_part_template

    two_part = [two_part_template(f.text) for f in agent]
    two_part_rate = sum(two_part) / n

    intensities = [f.intensity for f in agent]
    peak = max(intensities)
    peak_turn = intensities.index(peak) + 1

    # 峰值后 3 轮内是否降下来过
    later = intensities[peak_turn - 1 : peak_turn + 3]
    peak_relief = len(later) > 1 and any(v < peak for v in later[1:])

    # 断崖：agent 大幅波动而 user 没有。
    # 只排除「提问」——"几点开始的呀"在强度词上是 0 档，但它是正常的推进动作，
    # 不是情绪骤降；而「应声」不排除：对"我撑不住了"只回一个"嗯"就是断崖。
    _NEUTRAL_MOVES = {"提问"}
    jumps = 0
    for i in range(1, n):
        if agent[i].strategy in _NEUTRAL_MOVES:
            continue
        # 只把"短短一句就收了"算断崖。给建议/讲道理的长回复在情绪词上是 0 档，
        # 但它是投入的（arc-02 第 4 轮就是这样被误判的）
        if agent[i].length > 16:
            continue
        if abs(_delta(intensities, i)) >= 2 and abs(_delta(user_intensity, i)) <= 1:
            jumps += 1

    # 卡带：连续 3 轮同策略 + 同强度。
    # 排除「提问」——连续追问是**正确**的（尤其是安全场景：arc-05 里 agent
    # 连问三次"今晚他人在家吗/你身上有没有伤"，这是该做的，不是卡带）。
    # 真正的复读由 repeat_rate 兜底。
    stuck = 0
    for i in range(2, n):
        window = agent[i - 2 : i + 1]
        if any(f.strategy == "提问" for f in window):
            continue
        if len({f.strategy for f in window}) == 1 and len({f.intensity for f in window}) == 1:
            stuck += 1

    # 复读：自己比，不依赖调用方有没有给 previous
    repeats = 0
    for i in range(1, n):
        if check_repetition(agent[i - 1].text, agent[i].text):
            repeats += 1

    # 抢跑：agent 比 user 高太多
    lead = sum(
        1
        for a, u in zip(intensities, user_intensity)
        if a - u > 1
    )

    diversity = len({f.strategy for f in agent}) / n

    findings: dict[str, int] = {}
    for f in agent:
        for item in f.findings:
            findings[item.code] = findings.get(item.code, 0) + 1

    return ArcReport(
        turns=n,
        peak_turn=peak_turn,
        peak_intensity=peak,
        end_intensity=intensities[-1],
        peak_relief=peak_relief,
        relief_eligible=peak >= 2,
        jump_rate=jumps / max(1, n - 1),
        stuck_rate=stuck / max(1, n - 2),
        repeat_rate=repeats / n,
        lead_count=lead,
        diversity=diversity,
        question_rate=question_rate,
        two_part_rate=two_part_rate,
        opener_two_part=two_part[0] if two_part else False,
        findings=findings,
    )


def aggregate(reports: list[ArcReport]) -> dict:
    if not reports:
        return {}
    total_turns = sum(r.turns for r in reports)
    eligible = [r for r in reports if r.relief_eligible]
    return {
        "sessions": len(reports),
        "turns": total_turns,
        "relief_eligible": len(eligible),
        "peak_relief": sum(1 for r in eligible if r.peak_relief),
        "stuck_rate": sum(r.stuck_rate * r.turns for r in reports) / total_turns,
        "repeat_rate": sum(r.repeat_rate * r.turns for r in reports) / total_turns,
        "jump_rate": sum(r.jump_rate * r.turns for r in reports) / total_turns,
        "lead_count": sum(r.lead_count for r in reports),
        "diversity": sum(r.diversity for r in reports) / len(reports),
        "question_rate": sum(r.question_rate * r.turns for r in reports) / total_turns,
        "two_part_rate": sum(r.two_part_rate * r.turns for r in reports) / total_turns,
        "opener_two_part": sum(1 for r in reports if r.opener_two_part),
    }
