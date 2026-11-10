"""样本量计算：证明「这个差异我这套样本量测不出来」。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from checks.power import detectable_delta, required_n, verdict  # noqa: E402



class TestPower:
    def test_small_difference_needs_huge_sample(self):
        assert required_n(0.30, 0.24) > 500

    def test_large_difference_needs_few(self):
        assert required_n(0.90, 0.28) < 20

    def test_identical_is_zero(self):
        assert required_n(0.3, 0.3) == 0

    def test_detectable_delta_shrinks_with_n(self):
        assert detectable_delta(0.3, 600) < detectable_delta(0.3, 60)

    def test_detectable_delta_at_60_is_about_23pp(self):
        assert 0.20 < detectable_delta(0.3, 60) < 0.26

    def test_verdict_says_not_enough(self):
        assert verdict(60, 0.30, 0.24).startswith("不够")
        assert verdict(39, 0.90, 0.28).startswith("够")
