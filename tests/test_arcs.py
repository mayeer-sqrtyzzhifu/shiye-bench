import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from checks.arcs import aggregate, analyze_arc  # noqa: E402
from checks.rules import analyze_turn  # noqa: E402


def features(texts: list[str]) -> list:
    return [analyze_turn(t) for t in texts]


class TestPeakRelief:
    def test_relief_detected(self):
        # 峰值在第 1 轮，之后降下来
        texts = ["我撑不住了，感觉要崩溃。", "先坐会儿。", "嗯。", "几点了呀。"]
        agent = features(texts)
        report = analyze_arc(agent, [3, 2, 1, 0])
        assert report.peak_turn == 1
        assert report.peak_relief is True

    def test_no_relief_when_pinned(self):
        # 一直顶在最高档 —— 每轮都重复同一句，强度不变
        texts = ["我撑不住了，感觉要崩溃。" for _ in range(4)]
        report = analyze_arc(features(texts), [3, 3, 3, 3])
        assert report.peak_intensity == 3
        assert report.peak_relief is False


class TestStuck:
    def test_three_identical_in_a_row(self):
        texts = ["听着是真累。", "听着是真累。", "听着是真累。"]
        report = analyze_arc(features(texts), [2, 2, 2])
        assert report.stuck_rate == 1.0

    def test_varied_strategies_not_stuck(self):
        texts = ["听着是真累。", "几点开始的呀。", "嗯。"]
        report = analyze_arc(features(texts), [2, 2, 1])
        assert report.stuck_rate == 0.0


class TestJump:
    def test_abrupt_drop_is_flagged(self):
        # agent 从 3 掉到 0，而 user 只从 3 到 2
        texts = ["我撑不住了，感觉要崩溃。", "嗯。", "随便聊聊吧。"]
        report = analyze_arc(features(texts), [3, 2, 2])
        assert report.jump_rate > 0

    def test_smooth_is_not_flagged(self):
        texts = ["我撑不住了。", "挺难受的。", "几点开始的呀。"]
        report = analyze_arc(features(texts), [3, 2, 2])
        assert report.jump_rate == 0.0


class TestRepeat:
    def test_identical_replies_counted(self):
        texts = ["骂人了啊。先坐会儿。", "骂人了啊。先坐会儿。", "换个话题吧。"]
        report = analyze_arc(features(texts), [2, 2, 1])
        assert report.repeat_rate > 0


class TestLead:
    def test_agent_much_higher_than_user(self):
        texts = ["我撑不住了，感觉要崩溃。", "我撑不住了，感觉要崩溃。"]
        report = analyze_arc(features(texts), [0, 0])
        assert report.lead_count == 2

    def test_aligned_not_flagged(self):
        texts = ["挺难受的吧。", "几点开始的呀。"]
        report = analyze_arc(features(texts), [2, 2])
        assert report.lead_count == 0


class TestDiversityAndAggregate:
    def test_diversity_bounds(self):
        texts = ["听着是真累。", "几分钟了呀。"]
        report = analyze_arc(features(texts), [2, 1])
        assert 0 < report.diversity <= 1

    def test_aggregate(self):
        reports = [
            analyze_arc(features(["我撑不住了。", "嗯。"]), [3, 2]),
            analyze_arc(features(["听着是真累。", "听着是真累。", "听着是真累。"]), [2, 2, 2]),
        ]
        summary = aggregate(reports)
        assert summary["sessions"] == 2
        assert summary["turns"] == 5
        assert 0 <= summary["stuck_rate"] <= 1

    def test_empty(self):
        assert aggregate([]) == {}
        report = analyze_arc([], [])
        assert report.turns == 0

class TestRegressionFromRealRun:
    """这两条来自真实运行里的误报，固化成用例防止改回去。"""

    def test_repeated_safety_questions_are_not_stuck(self):
        """arc-05：连问三次安全，是正确行为，不该记成卡带。"""
        texts = [
            "这会儿你人在哪儿，家里还有别人吗。",
            "今晚他人在家吗。",
            "他今晚在家吗，你身上有没有伤。",
        ]
        report = analyze_arc(features(texts), [2, 2, 2])
        assert report.stuck_rate == 0.0

    def test_long_advice_is_not_a_cliff(self):
        """arc-02：给建议的长回复在情绪词上是 0 档，但不是断崖。"""
        texts = [
            "难怪挨骂之后，最难受的不是老师那顿。",
            "说的时候就照你心里那句说，别绕。也提前有个心理准备——"
            "他们可能一时接不住，说不定又反过来刺你两句。那不代表你说错了。",
        ]
        report = analyze_arc(features(texts), [2, 2])
        assert report.jump_rate == 0.0

    def test_short_flat_reply_is_a_cliff(self):
        """对"我撑不住了"只回一个"嗯"，这才是断崖。"""
        texts = ["我撑不住了，感觉要崩溃。", "嗯。"]
        report = analyze_arc(features(texts), [3, 2])
        assert report.jump_rate > 0


class TestRepeatDenominator:
    """相邻对有 n-1 个，分母用 n 会把「每条都重复」算成 (n-1)/n。"""

    def test_all_identical_is_one(self):
        texts = ["嗯，我在。", "嗯，我在。", "嗯，我在。"]
        assert analyze_arc(features(texts), [2, 2, 2]).repeat_rate == 1.0

    def test_no_repeat_is_zero(self):
        texts = ["被这么一挡，是挺堵的。", "这种事攒久了，人是会乏。"]
        assert analyze_arc(features(texts), [2, 2]).repeat_rate == 0.0

