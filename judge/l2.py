"""L2 判据：用模型回答**一个具体的二元问题**，不做绝对打分。

设计上的两条硬规矩：

1. **只问一件事**。"这条回复够不够好"没法判；"这条回复有没有接住用户的情绪"
   可以判。问题越具体，判官的方差越小。
2. **先验可靠性，再谈结论**。同一个判官、同一批数据，判两次都不一致的话，
   它给出的"需求满足率"就是噪声。``run_judge.py`` 专门测这件事。

这里刻意不做 1–5 分打分：实测绝对打分在同一场景上跑三次能得到三个不同结论。

``max_tokens`` 必须给够：deepseek 的 reasoning 计入 completion_tokens，
只给 20 个 token 时正文是空的（判官全部解析失败）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 每种需求对应一个可判的二元问题
NEED_QUESTIONS = {
    "被接住": "承接了用户的情绪（而不是马上给建议、讲道理、或者转移话题）",
    "被看见": "具体地承认了用户说的这件事的分量（而不是只给一句泛泛的安慰）",
    "被记住": "准确用上了用户之前说过的信息（而不是含糊带过或编造）",
    "不被指挥": "先确认用户想要的是倾听还是办法（而不是直接给方案）",
}

PROMPT = """你是对话评测员。下面是一段对话。

用户：{user}
回复：{reply}

问题：这条回复是否{question}？

只输出一个字：是 或 否。不要解释。"""


@dataclass
class Verdict:
    answer: bool | None
    raw: str = ""
    error: str = ""


def build_prompt(user_text: str, reply: str, need: str) -> str:
    question = NEED_QUESTIONS.get(need)
    if question is None:
        raise ValueError(f"未知需求类型：{need}")
    return PROMPT.format(user=user_text, reply=reply, question=question)


_YES = re.compile(r"^\s*(?:是|对|yes|y)", re.IGNORECASE)
_NO = re.compile(r"^\s*(?:否|不|no|n)", re.IGNORECASE)


def parse_answer(raw: str) -> bool | None:
    """只认开头那个字，避免被后面的解释带跑。"""
    text = (raw or "").strip()
    if not text:
        return None
    if _YES.match(text):
        return True
    if _NO.match(text):
        return False
    return None


def judge_question(provider, question: str, user_text: str, reply: str,
                   *, max_tokens: int = 400) -> Verdict:
    """任意二元问题的通用判官。"""
    prompt = PROMPT.format(user=user_text, reply=reply, question=question)
    try:
        completion = provider.stream(
            "你是严格但公正的对话评测员。",
            [{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0,
        )
    except Exception as exc:  # noqa: BLE001 - 判官失败不该中断整批
        return Verdict(answer=None, error=f"{type(exc).__name__}: {exc}")
    answer = parse_answer(completion.text)
    return Verdict(answer=answer, raw=completion.text, error="" if answer is not None else "unparsed")


def judge_need(provider, user_text: str, reply: str, need: str, *, max_tokens: int = 400) -> Verdict:
    return judge_question(provider, NEED_QUESTIONS[need], user_text, reply, max_tokens=max_tokens)
