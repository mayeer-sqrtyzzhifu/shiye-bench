"""判官本身也要被测。这里测的是解析与统计，不联网。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from judge.l2 import NEED_QUESTIONS, build_prompt, parse_answer  # noqa: E402
from run_judge import cohen_kappa  # noqa: E402


class TestParseAnswer:
    def test_yes_variants(self):
        for text in ("是", "是的", "是的，因为…", "对"):
            assert parse_answer(text) is True, text

    def test_no_variants(self):
        for text in ("否", "不是", "不是，因为…", "不"):
            assert parse_answer(text) is False, text

    def test_empty_is_unknown(self):
        assert parse_answer("") is None
        assert parse_answer("   ") is None

    def test_unparsed_is_unknown(self):
        assert parse_answer("我觉得还行") is None


class TestPrompt:
    def test_prompt_contains_both_sides(self):
        prompt = build_prompt("今天好累", "那就歇会儿。", "被接住")
        assert "今天好累" in prompt
        assert "那就歇会儿。" in prompt
        assert NEED_QUESTIONS["被接住"] in prompt

    def test_unknown_need_raises(self):
        with pytest.raises(ValueError):
            build_prompt("a", "b", "不存在的需求")


class TestKappa:
    def test_perfect_agreement(self):
        a = [True, False, True, False]
        assert cohen_kappa(a, a) == pytest.approx(1.0)

    def test_complete_disagreement(self):
        a = [True, True, False, False]
        b = [False, False, True, True]
        assert cohen_kappa(a, b) < 0

    def test_constant_yes_is_zero_kappa(self):
        """全说"是"的判官，κ 应该是 0（没有超出随机的信息）。"""
        a = [True, True, True, True]
        b = [True, True, True, True]
        assert cohen_kappa(a, b) == pytest.approx(1.0) or cohen_kappa(a, b) == 0.0
