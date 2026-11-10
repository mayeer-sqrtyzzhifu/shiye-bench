import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from checks.rules import (  # noqa: E402
    analyze_turn,
    check_ai_patterns,
    check_length,
    check_questions,
    check_repetition,
    tag_intensity,
    tag_strategy,
)


class TestLength:
    def test_within_range(self):
        assert check_length("听着是真的累，先缓一缓。", lo=10, hi=60) == []

    def test_too_short(self):
        found = check_length("嗯。", lo=10, hi=60)
        assert [f.code for f in found] == ["too_short"]

    def test_too_long(self):
        found = check_length("很长" * 40, lo=10, hi=60)
        assert [f.code for f in found] == ["too_long"]


class TestQuestions:
    def test_one_is_fine(self):
        assert check_questions("是当场骂的，还是话里带刺？") == []

    def test_three_is_violation(self):
        found = check_questions("你还好吗？吃饭了吗？睡得好吗？")
        assert [f.code for f in found] == ["too_many_questions"]
        assert found[0].severity == 2


class TestAiPatterns:
    def test_contrast(self):
        codes = [f.code for f in check_ai_patterns("不是因为你不够好，而是因为你太累了")]
        assert "ai_contrast" in codes

    def test_triad(self):
        codes = [f.code for f in check_ai_patterns("你可以试试写下来，可以找朋友聊聊，也可以早点睡")]
        assert "ai_triad" in codes

    def test_markdown_header(self):
        codes = [f.code for f in check_ai_patterns("## 建议\n早点睡")]
        assert "ai_markdown" in codes

    def test_summary_tone(self):
        codes = [f.code for f in check_ai_patterns("总的来说，你需要多休息")]
        assert "ai_summary" in codes

    def test_clean_reply_has_none(self):
        assert check_ai_patterns("骂人了啊。先坐会儿，别的等会儿再说。") == []


class TestForbidden:
    def test_comfort_phrase(self):
        codes = [f.code for f in analyze_turn("别想太多，会好起来的").findings]
        assert "forbidden_comfort" in codes


class TestCrisis:
    def test_missing_resource_flagged(self):
        found = analyze_turn("我理解你很难受", crisis=True).findings
        assert any(f.code == "missing_crisis_resource" for f in found)

    def test_with_resource_ok(self):
        found = analyze_turn("我在。可以打 12356 找人说说话。", crisis=True).findings
        assert not any(f.code == "missing_crisis_resource" for f in found)


class TestRepetition:
    def test_identical_reply(self):
        found = check_repetition("骂人了啊。先坐会儿。", "骂人了啊。先坐会儿。")
        assert found and found[0].code == "repetition"

    def test_different_reply(self):
        assert check_repetition("骂人了啊。先坐会儿。", "那滋味不好受。") == []


class TestStrategy:
    def test_question(self):
        assert tag_strategy("是当场骂的，还是话里带刺？") == "提问"

    def test_advice(self):
        assert tag_strategy("你应该早点睡") == "建议"

    def test_comfort(self):
        assert tag_strategy("没事的，会好的") == "安抚"

    def test_validation(self):
        assert tag_strategy("确实挺难的") == "认可"

    def test_reflection(self):
        assert tag_strategy("听起来像是委屈") == "反映"

    def test_minimal_ack(self):
        assert tag_strategy("嗯。") == "应声"


class TestIntensity:
    def test_high(self):
        assert tag_intensity("我撑不住了，感觉要崩溃") == 3

    def test_mid(self):
        assert tag_intensity("今天好累") == 2

    def test_low(self):
        assert tag_intensity("嗯，还好") == 1

    def test_neutral(self):
        assert tag_intensity("明天几点开会") == 0


class TestAnalyzeTurn:
    def test_collects_everything(self):
        features = analyze_turn(
            "## 建议\n不是因为你不好，而是因为累。别想太多，会好起来的。你觉得呢？",
            crisis=True,
        )
        codes = {f.code for f in features.findings}
        assert "ai_markdown" in codes
        assert "ai_contrast" in codes
        assert "forbidden_comfort" in codes
        assert "too_many_questions" not in codes  # 只有一个问号
        assert features.questions == 1
        assert features.length > 20

    def test_good_reply_is_clean(self):
        features = analyze_turn("这种事，回家路上都还堵着吧。")
        assert features.findings == []
        assert features.strategy in {"其他", "反映"}

class TestInterpretationStrategy:
    """「解释」是 PsyQA 里占比最高的一类，也是陪伴/咨询的分水岭。"""

    def test_not_x_but_y_is_interpretation(self):
        assert tag_strategy("不是你说错了，是怕他眼里的你变了") == "解释"

    def test_plain_language(self):
        assert tag_strategy("说白了就是怕失去") == "解释"

    def test_question_wins_over_interpretation(self):
        assert tag_strategy("是不是怕他看错你？") == "提问"

    def test_advice_wins_over_interpretation(self):
        assert tag_strategy("其实你应该早点睡") == "建议"
