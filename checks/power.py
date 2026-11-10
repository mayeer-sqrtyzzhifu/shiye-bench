"""样本量计算：**这个差异，我这套样本量能不能测出来。**

二十几轮里反复出现同一个问题——「改前 30%、改后 24%，算不算有用？」
凭直觉会说「降了 6 个点，当然有用」，但 60 条的样本根本撑不起这个结论。

这里给两个方向的计算：

* ``required_n``：想在给定把握下测出某个差异，每组需要多少条
* ``detectable_delta``：给定样本量，能测出的最小差异是多少

公式用双比例检验的正态近似（够用，且有闭式解，不需要模拟）。
"""

from __future__ import annotations

import math

# 双侧 95% 对应 1.96；80% 把握度对应 0.84
Z_ALPHA = 1.96
Z_POWER = 0.84


def required_n(p1: float, p2: float, *, z_alpha: float = Z_ALPHA, z_power: float = Z_POWER) -> int:
    """两组比例差 p1 - p2，每组需要多少样本。

    用合并比例的近似：n = (z_a + z_b)^2 * (p1(1-p1) + p2(1-p2)) / (p1-p2)^2
    """
    if p1 == p2:
        return 0
    variance = p1 * (1 - p1) + p2 * (1 - p2)
    n = (z_alpha + z_power) ** 2 * variance / (p1 - p2) ** 2
    return math.ceil(n)


def detectable_delta(p: float, n: int, *, z_alpha: float = Z_ALPHA, z_power: float = Z_POWER) -> float:
    """每组 n 条时，在基准比例 p 附近能测出的最小绝对差异。"""
    if n <= 0:
        return 1.0
    variance = 2 * p * (1 - p)
    return (z_alpha + z_power) * math.sqrt(variance / n)


def verdict(n: int, p1: float, p2: float) -> str:
    """一句话判断：这个样本量够不够。"""
    need = required_n(p1, p2)
    if need == 0:
        return "两组相同"
    if n >= need:
        return f"够（需要 {need} 条/组，有 {n}）"
    return f"不够（需要 {need} 条/组，只有 {n}）"
