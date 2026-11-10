"""具体性度量：回复有没有接住用户说过的**具体内容**。

动机：p4→p5 去掉生活细节之后，成对判据偏向 p4（2:1，但不显著）。
一个自然的解释是「p5 变通用了、不再贴着用户说的东西」。

这个模块就是用来检验那句解释的：量回复里有多少词是用户刚说过的。
如果两版一样，那「变通用」的解释就不成立，不该据此改产品。

算法：中文二元组覆盖率 = 回复里的二元组有多少比例在用户发言里出现过。
不用分词，避免引入依赖；二元组对中文够用。
"""

from __future__ import annotations

import re

_CJK = re.compile(r"[\u4e00-\u9fff]")


def _bigrams(text: str) -> set[str]:
    clean = "".join(ch for ch in (text or "") if _CJK.match(ch))
    return {clean[i : i + 2] for i in range(len(clean) - 1)}


def grounding(user_text: str, reply: str) -> float:
    """回复中的二元组有多少比例来自用户发言。范围 0–1。"""
    reply_grams = _bigrams(reply)
    if not reply_grams:
        return 0.0
    return len(_bigrams(user_text) & reply_grams) / len(reply_grams)


def average_grounding(pairs: list[tuple[str, str]]) -> float:
    values = [grounding(u, r) for u, r in pairs if (r or "").strip()]
    return sum(values) / len(values) if values else 0.0
