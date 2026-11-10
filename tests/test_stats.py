"""统计工具的测试：这些函数一旦算错，所有结论都会错。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from checks.stats import (  # noqa: E402
    cohen_h,
    cohen_kappa,
    mcnemar,
    min_detectable,
    required_n,
    sign_test,
    wilson,
)


class TestWilson:
    def test_bounds_contain_estimate(self):
        lo, hi = wilson(3, 4)
        assert 0 <= lo <= 0.75 <= hi <= 1

    def test_small_sample_is_wide(self):
        lo, hi = wilson(3, 4)
        assert hi - lo > 0.5

    def test_large_sample_is_tight(self):
        lo, hi = wilson(300, 600)
        assert hi - lo < 0.1

    def test_zero_total(self):
        assert wilson(0, 0) == (0.0, 0.0)

    def test_all_success_does_not_reach_one(self):
        """5/5 的区间上界到不了 100% —— 这正是它比点估计诚实的地方。"""
        lo, hi = wilson(5, 5)
        assert lo > 0.4 and hi == 1.0 and lo < 0.9


class TestKappa:
    def test_perfect(self):
        a = [True, False, True, False]
        assert cohen_kappa(a, a) == pytest.approx(1.0)

    def test_opposite_is_negative(self):
        assert cohen_kappa([True, True, False, False], [False, False, True, True]) < 0

    def test_all_false_is_undefined(self):
        """两次都全判否：一致率 100%，但**没有信息**。

        返回 1.0 会把「这个指标从不触发」误报成「完美可靠」——
        指标体检里「编造生活」就因此被误判成可用。
        """
        assert cohen_kappa([False] * 4, [False] * 4) is None

    def test_length_mismatch(self):
        assert cohen_kappa([True], [True, False]) is None


class TestMcNemar:
    def test_no_change(self):
        a = [True, False, True, False]
        result = mcnemar(a, a)
        assert result.changed == 0 and result.p_value == pytest.approx(1.0)

    def test_one_sided_change_is_significant(self):
        # 10 条从「是」变「否」，0 条反向
        a = [False] * 10 + [True] * 10
        b = [True] * 10 + [True] * 10
        result = mcnemar(a, b)
        assert result.only_b == 10 and result.only_a == 0
        assert result.p_value < 0.01

    def test_balanced_change_is_not(self):
        a = [True] * 5 + [False] * 5
        b = [False] * 5 + [True] * 5
        result = mcnemar(a, b)
        assert result.p_value > 0.9


class TestSignTest:
    def test_even_split(self):
        assert sign_test(5, 5) == pytest.approx(1.0)

    def test_lopsided(self):
        assert sign_test(14, 7) < 0.2

    def test_no_data(self):
        assert sign_test(0, 0) == pytest.approx(1.0)


class TestPower:
    def test_small_effect_needs_many(self):
        assert required_n(0.30, 0.24) > 500

    def test_large_effect_needs_few(self):
        assert required_n(0.90, 0.28) < 20

    def test_floor_shrinks_with_n(self):
        assert min_detectable(0.3, 600) < min_detectable(0.3, 60)

    def test_floor_at_60_is_about_a_quarter(self):
        assert 0.2 < min_detectable(0.3, 60) < 0.3


class TestCohenH:
    def test_small_effect(self):
        assert cohen_h(0.50, 0.45) < 0.2

    def test_large_effect(self):
        assert cohen_h(0.90, 0.28) > 0.8

    def test_symmetric(self):
        assert cohen_h(0.8, 0.3) == pytest.approx(cohen_h(0.3, 0.8))
