"""成对判据：同一句用户发言，两个版本的回复，哪个更好。

为什么需要它：比例对比测不出细粒度差异。
算过——想测 6pp 的差异，每组要 855 条（见 ``checks/power.py``）。
成对比较不吃基线比例，方差小得多，100–200 对就有分辨力。

设计上守两条：

1. **打乱左右**。固定顺序会让判官偏爱某一边（位置效应）。
2. **允许平局**。硬逼二选一会把噪声放大成信号。

用法见 ``run_pairwise.py``。
"""

from __future__ import annotations

import random
from dataclasses import dataclass

PROMPT = """下面是一个人的一句话，以及两种回应。

用户：{user}

回应 A：
{a}

回应 B：
{b}

问题：哪一个回应更好地{question}？

只输出一个字母：A、B，或 S（两者差不多）。不要解释。"""


@dataclass
class PairVerdict:
    winner: str | None = None  # "A" / "B" / "S"
    raw: str = ""
    error: str = ""


def build_prompt(user: str, a: str, b: str, question: str) -> str:
    return PROMPT.format(user=user, a=a, b=b, question=question)


def parse_choice(raw: str) -> str | None:
    text = (raw or "").strip().upper()
    if not text:
        return None
    head = text[0]
    if head in "AB":
        return head
    if head == "S" or text.startswith("SAME") or text.startswith("相同"):
        return "S"
    return None


def judge_pair(
    provider,
    user: str,
    left: str,
    right: str,
    question: str,
    *,
    swap: bool = False,
    max_tokens: int = 400,
) -> tuple[PairVerdict, str]:
    """返回 (判定, 哪一个版本胜出)。

    ``swap=True`` 时把两个回应换个位置，若模型仍然选中"同一个内容"，
    说明它不是靠位置猜的。
    """
    a, b = (right, left) if swap else (left, right)
    prompt = build_prompt(user, a, b, question)
    try:
        completion = provider.stream(
            "你是严格但公正的对话评测员。",
            [{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0,
        )
    except Exception as exc:  # noqa: BLE001
        return PairVerdict(error=f"{type(exc).__name__}: {exc}"), ""

    choice = parse_choice(completion.text)
    if choice is None:
        return PairVerdict(raw=completion.text, error="unparsed"), ""

    # 把 A/B 映射回 left/right
    if choice == "S":
        winner = "tie"
    elif choice == "A":
        winner = "right" if swap else "left"
    else:
        winner = "left" if swap else "right"
    return PairVerdict(winner=choice, raw=completion.text), winner
