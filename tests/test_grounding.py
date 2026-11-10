"""具体性度量测试。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from checks.grounding import average_grounding, grounding  # noqa: E402



class TestGrounding:
    def test_reuses_user_words(self):
        s = grounding("我养的猫叫团子", "团子挺可爱的。")
        assert s >= 0.2

    def test_generic_reply_scores_zero(self):
        assert grounding("我养的猫叫团子", "嗯，我明白。") == 0.0

    def test_empty_reply(self):
        assert grounding("随便", "") == 0.0

    def test_average_ignores_blank(self):
        pairs = [("猫叫团子", "团子"), ("", ""), ("今天很累", "那就歇会儿")]
        assert 0 <= average_grounding(pairs) <= 1

    def test_range_is_bounded(self):
        for user, reply in [("a", "b"), ("我们今天聊了很多事情", "我们今天聊了很多")]:
            assert 0.0 <= grounding(user, reply) <= 1.0
