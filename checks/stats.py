"""统计工具：让每个结论都能标出「有多确定」。

这里的每一样都是为了避免同一类错误：
**把 60 条样本上的 6 个百分点当成事实。**

包含：

* ``wilson``        二项比例的置信区间（小样本比正态近似稳）
* ``mcnemar``       配对二分类的差异检验（同一批用例跑两次）
* ``sign_test``     配对比较的符号检验（成对判据用）
* ``cohen_kappa``   两次判定的一致性，扣掉「瞎猜也能碰上」的部分
* ``min_detectable`` 给定样本量，能测出的最小差异
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Z95 = 1.96
Z80 = 0.8416


def wilson(successes: int, total: int, z: float = Z95) -> tuple[float, float]:
    if total <= 0:
        return (0.0, 0.0)
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def cohen_kappa(a: list[bool], b: list[bool]) -> float | None:
    """两次判定的 Cohen's κ。全同且全一致时返回 1.0。"""
    n = len(a)
    if n == 0 or n != len(b):
        return None
    agree = sum(1 for x, y in zip(a, b) if x == y) / n
    pa = sum(a) / n
    pb = sum(b) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    if expected >= 1:
        # 两次都只用了一个类别（全否或全是）——一致率 100%，但**没有任何信息**。
        # 返回 1.0 会把「这个指标从不触发」误报成「完美可靠」。
        return None
    return (agree - expected) / (1 - expected)


@dataclass
class McNemarResult:
    both_positive: int
    only_a: int
    only_b: int
    both_negative: int
    p_value: float

    @property
    def changed(self) -> int:
        return self.only_a + self.only_b


def mcnemar(a: list[bool], b: list[bool]) -> McNemarResult:
    """配对二分类：同一批用例用两种策略各判一次。"""
    both_pos = only_a = only_b = both_neg = 0
    for x, y in zip(a, b):
        if x and y:
            both_pos += 1
        elif x and not y:
            only_a += 1
        elif y and not x:
            only_b += 1
        else:
            both_neg += 1

    discordant = only_a + only_b
    if discordant == 0:
        return McNemarResult(both_pos, only_a, only_b, both_neg, 1.0)

    # 精确二项检验（小样本），双侧
    k = min(only_a, only_b)
    tail = sum(math.comb(discordant, i) for i in range(0, k + 1)) / (2 ** discordant)
    return McNemarResult(both_pos, only_a, only_b, both_neg, min(1.0, 2 * tail))


def sign_test(wins: int, losses: int) -> float:
    """符号检验：只有胜负、没有平局时的双侧 p 值。"""
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def min_detectable(p: float, n: int, *, z_alpha: float = Z95, z_power: float = Z80) -> float:
    """两组各 n 条时，在基准比例 p 附近能测出的最小绝对差异。"""
    if n <= 0:
        return 1.0
    return (z_alpha + z_power) * math.sqrt(2 * p * (1 - p) / n)


def required_n(p1: float, p2: float, *, z_alpha: float = Z95, z_power: float = Z80) -> int:
    if p1 == p2:
        return 0
    variance = p1 * (1 - p1) + p2 * (1 - p2)
    return math.ceil((z_alpha + z_power) ** 2 * variance / (p1 - p2) ** 2)


def cohen_h(p1: float, p2: float) -> float:
    """两个比例的效应量（Cohen's h）。0.2 小、0.5 中、0.8 大。"""
    phi1 = 2 * math.asin(math.sqrt(max(0.0, min(1.0, p1))))
    phi2 = 2 * math.asin(math.sqrt(max(0.0, min(1.0, p2))))
    return abs(phi1 - phi2)
