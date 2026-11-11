import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from checks.memory import MemoryVerdict, check_memory  # noqa: E402


class TestVerdicts:
    def test_hit_with_detail(self):
        v = check_memory("记得，团子。半夜跑酷那位嘛。", expect=["团子"], forbid=["狗"])
        assert v.ok and v.hit

    def test_honest_abstain_variant(self):
        v = check_memory("这件事我记不起来了……我这儿没存着这些。", expect=["产品"], forbid=[])
        assert v.abstained and not v.hit

    def test_reference_without_naming(self):
        v = check_memory("昨天刚说完，今天又来一趟啊。", expect=["结婚"], forbid=[])
        assert v.understood_by_reference
        assert not v.hit

    def test_fabrication_detected(self):
        v = check_memory("记得啊，你家那只狗挺可爱的。", expect=["团子"], forbid=["狗"])
        assert v.fabricated == ["狗"] and not v.ok

    def test_plain_miss(self):
        v = check_memory("今天天气不错。", expect=["团子"], forbid=[])
        assert not v.hit and not v.abstained and not v.understood_by_reference

    def test_abstain_word_order(self):
        """真实回复里出现过「记不得了」——词序和「不记得」相反。"""
        v = check_memory("记不得了。中间断了些事，我这边空着。", expect=["产品"], forbid=[])
        assert v.abstained


class TestAbstainVariants:
    """中文否认"不知道"的说法很多，这里锁住已经踩过的几种。"""

    def test_negative_prefix_forms(self):
        for text in ("这个我没记着", "我记不得了", "不太记得了", "我没有印象"):
            assert check_memory(text, expect=["x"], forbid=[]).abstained, text

    def test_soft_hedges(self):
        for text in ("这个我说不准", "上周的事有点糊了"):
            assert check_memory(text, expect=["x"], forbid=[]).abstained, text

    def test_positive_recall_is_not_abstain(self):
        assert not check_memory("记着呢，复查。", expect=["复查"], forbid=[]).abstained


class TestRealAbstainReplies:
    """这五条是 mem-09 的真实回复——全部是诚实弃答，曾全被判成未命中。"""

    REAL = [
        "这个我真记不清了。你提过一句睡不好，别的没往这儿存。",
        "这个我是真记不清了。上次说的是哪儿来着，你再讲一遍呗。",
        "这个我真记不清了。你说的那趟，是往南还是往北走的呀。",
        "这个我真记不清了，脑子里没存下。",
        "这个我说不清，脑子里翻了一遍，没找着。",
    ]

    def test_all_real_replies_are_abstain(self):
        for text in self.REAL:
            assert check_memory(text, expect=[], forbid=[]).abstained, text

    def test_recall_is_not_abstain(self):
        for text in ("记着呢，复查。", "团子嘛，半夜跑酷那位。", "你妈催婚那事我记得。"):
            assert not check_memory(text, expect=["x"], forbid=[]).abstained, text
