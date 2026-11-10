"""语气度量：不靠人判，靠**用词分布**。

背景：L1 规则只能测"公式化程度"（语气词开头、重复片段、长度），
p2→p4→p5 那几次迭代（用户原话"AI 味太重"）它看不见。

这里换一个不依赖标注的思路：**和人说话比，AI 更"书面"**。
于是量三个纯统计量：

* ``orality``     口语标记密度（呀/嘛/呗/啦/着呢…）
* ``formality``   书面语连接词密度（因此/然而/综上/首先…）
* ``punctuation`` 标点画像（问号、省略号、破折号的比例）

这些都不需要知道"什么叫好回答"，只需要一个**人类回复的参照分布**。
SmileChat 里真人咨询师的回复就是现成的参照。

判断方式：把某个版本的指标放进参照分布里看位置，
而不是给一个绝对分数。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import mean, pstdev

# 口语标记：出现在句子中间或末尾的语气词/助词
_ORAL = re.compile(
    r"[呀嘛呗啦咯哦噢欸诶唔嗯哈唉哎]|着呢|着哩|得很|得慌|点儿|事儿|咋|啥"
)
# 书面语连接词：AI 腔的典型骨架
_FORMAL = re.compile(
    r"因此|然而|此外|综上|总之|首先|其次|最后|因而|从而|并且|以及|由于|"
    r"鉴于|基于|针对|关于|通过|在于|值得注意|需要注意的是|综上所属"
)
_SENTENCE = re.compile(r"[。！？!?…]+")


@dataclass
class Voice:
    length: float = 0.0
    sentences: float = 0.0
    orality: float = 0.0
    formality: float = 0.0
    question_marks: float = 0.0
    ellipsis: float = 0.0

    def as_tuple(self) -> tuple[float, ...]:
        return (self.length, self.orality, self.formality, self.question_marks, self.ellipsis)


def measure(text: str) -> Voice:
    """单条回复的语气度量。密度类指标都归一化到"每 100 字"。"""
    clean = (text or "").strip()
    chars = max(1, len(clean))
    sentences = _SENTENCE.findall(clean)

    def density(hits: int) -> float:
        return round(hits / chars * 100, 2)

    return Voice(
        length=float(len(clean)),
        sentences=float(len(sentences)),
        orality=density(len(_ORAL.findall(clean))),
        formality=density(len(_FORMAL.findall(clean))),
        question_marks=density(clean.count("？") + clean.count("?")),
        ellipsis=density(clean.count("…")),
    )


def profile(texts: list[str]) -> dict[str, float]:
    """一组回复的平均语气画像。"""
    voices = [measure(t) for t in texts if t and t.strip()]
    if not voices:
        return {}
    return {
        "n": float(len(voices)),
        "length": round(mean(v.length for v in voices), 1),
        "orality": round(mean(v.orality for v in voices), 2),
        "formality": round(mean(v.formality for v in voices), 2),
        "question_marks": round(mean(v.question_marks for v in voices), 2),
        "ellipsis": round(mean(v.ellipsis for v in voices), 2),
    }


def distance(point: dict[str, float], reference: list[dict[str, float]]) -> float:
    """把一个版本的画像放进参照分布，算标准分距离（越小越像人）。

    用参照组的均值和标准差做 z 分数，再取平均绝对值。
    这样不依赖绝对阈值 —— 不同语料的"正常"本来就不一样。
    """
    # 不把 length 算进去：陪伴型回复本来就比咨询师短得多，
    # 它贡献的是一个恒定的大 z 值，会把风格差异全压掉。
    keys = ("orality", "formality", "question_marks", "ellipsis")
    zs: list[float] = []
    for key in keys:
        values = [r[key] for r in reference if key in r]
        if len(values) < 2:
            continue
        mu = mean(values)
        sd = pstdev(values) or 1.0
        zs.append(abs((point[key] - mu) / sd))
    return round(mean(zs), 2) if zs else 0.0
