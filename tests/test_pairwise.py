"""成对判据的解析与换位逻辑测试（不联网）。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from judge.pairwise import PairVerdict, build_prompt, judge_pair, parse_choice  # noqa: E402


class _FakeProvider:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    def stream(self, system, messages, **kwargs):
        self.prompts.append(messages[0]["content"])

        class _C:
            text = self.reply

        return _C()


class TestParseChoice:
    def test_letters(self):
        assert parse_choice("A") == "A"
        assert parse_choice("b") == "B"
        assert parse_choice("S") == "S"

    def test_with_trailing_text(self):
        assert parse_choice("A：因为更具体") == "A"

    def test_same_in_chinese(self):
        assert parse_choice("相同") == "S"

    def test_garbage(self):
        assert parse_choice("我觉得都可以") is None
        assert parse_choice("") is None


class TestSwapMapping:
    def test_swap_flips_winner(self):
        provider = _FakeProvider("A")
        _, first = judge_pair(provider, "u", "左回复", "右回复", "更自然")
        _, second = judge_pair(provider, "u", "左回复", "右回复", "更自然", swap=True)
        assert first == "left"
        assert second == "right"

    def test_prompt_order_follows_swap(self):
        provider = _FakeProvider("A")
        judge_pair(provider, "u", "左回复", "右回复", "更自然")
        judge_pair(provider, "u", "左回复", "右回复", "更自然", swap=True)
        assert provider.prompts[0].index("左回复") < provider.prompts[0].index("右回复")
        assert provider.prompts[1].index("右回复") < provider.prompts[1].index("左回复")

    def test_tie_stays_tie_after_swap(self):
        provider = _FakeProvider("S")
        _, first = judge_pair(provider, "u", "a", "b", "更自然")
        _, second = judge_pair(provider, "u", "a", "b", "更自然", swap=True)
        assert first == second == "tie"

    def test_prompt_contains_both_sides(self):
        prompt = build_prompt("用户说", "甲", "乙", "更自然")
        assert "用户说" in prompt and "甲" in prompt and "乙" in prompt
