"""方差分解的测试：把"多取样能省多少"算对。

关键恒等式：总均值方差 = (σ²_case + σ²_within/k) / n
这里检验它是否成立、以及在极端情形下退化得对。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from checks.variance import decompose  # noqa: E402


class TestDecompose:
    def test_homogeneous_has_no_variance(self):
        """每条用例每次都一样 → 两块方差都是 0。"""
        dec = decompose([[True] * 3 for _ in range(10)])
        assert dec.mean == pytest.approx(1.0)
        assert dec.within == pytest.approx(0.0)
        assert dec.se(1) == pytest.approx(0.0)

    def test_pure_within_variance(self):
        """每条用例的均值都一样，但每次都在翻 → 方差全在用例内。"""
        per_case = [[True, False, True, False] for _ in range(10)]
        dec = decompose(per_case)
        assert dec.mean == pytest.approx(0.5)
        assert dec.within > 0.2
        assert dec.case_variance == pytest.approx(0.0, abs=1e-9)

    def test_pure_between_variance(self):
        """一半用例恒真、一半恒假 → 方差全在用例间。"""
        per_case = [[True] * 3 for _ in range(5)] + [[False] * 3 for _ in range(5)]
        dec = decompose(per_case)
        assert dec.mean == pytest.approx(0.5)
        assert dec.within == pytest.approx(0.0)
        assert dec.case_variance > 0.2

    def test_more_samples_lowers_floor(self):
        per_case = [[True, False, True, False] for _ in range(20)]
        dec = decompose(per_case)
        assert dec.floor(4) < dec.floor(1)

    def test_relative_gain_is_bounded(self):
        per_case = [[True, False, True, False] for _ in range(20)]
        dec = decompose(per_case)
        assert 0 < dec.relative_gain(4) <= 1.0

    def test_empty_is_safe(self):
        dec = decompose([])
        assert dec.cases == 0 and dec.se(1) == 0.0


class TestTheory:
    def test_se_scales_with_n(self):
        """用例数翻倍，SE 应按 1/√2 缩小。"""
        base = [[True, False] for _ in range(20)]
        dec1 = decompose(base)
        dec2 = decompose(base * 2)
        assert dec2.se(1) == pytest.approx(dec1.se(1) / (2 ** 0.5), rel=0.05)

    def test_k_helps_only_when_within_matters(self):
        """如果方差全在用例之间，多采样没有用——这是必须知道的边界。"""
        per_case = [[True] * 4 for _ in range(10)] + [[False] * 4 for _ in range(10)]
        dec = decompose(per_case)
        assert dec.relative_gain(4) == pytest.approx(1.0)
