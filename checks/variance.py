"""方差分解：**多采几次样，到底能省多少。**

前提（见 ``docs/measurement.md``）：同一个输入，模型每次输出都不一样。
所以一条用例的结果不是一个数，是一个分布。

把每条用例采 k 次，就把总方差拆成两块：

```
每条用例的观测方差  = 用例之间的差异（σ²_case） + 用例内部的抖动（σ²_within）
```

* ``σ²_case``：有的用例天生容易触发某个指标（难易不同）
* ``σ²_within``：同一条用例重复生成时自己变

**总均值的方差** = (σ²_case + σ²_within / k) / n

只要知道这两块，就能算出"k 从 1 提到 3，可测下限降多少"，
不必真的去跑两轮对比——跑一轮 k 次就够。
"""

from __future__ import annotations

from dataclasses import dataclass

from .stats import min_detectable


@dataclass
class Decomposition:
    cases: int
    samples: int
    between: float  # σ²_case + σ²_within / k
    within: float  # σ²_within
    mean: float

    @property
    def case_variance(self) -> float:
        """去掉内部抖动后的"用例难度"方差，不能为负。"""
        return max(0.0, self.between - self.within / self.samples)

    def se(self, k: int) -> float:
        """每用例采 k 次时，总均值的标准误。"""
        if self.cases <= 0:
            return 0.0
        total = self.case_variance + self.within / max(1, k)
        return (total / self.cases) ** 0.5

    def floor(self, k: int) -> float:
        """每用例采 k 次时，能测出的最小差异（两组比较，80% 把握）。"""
        # min_detectable 输入的是"每组样本量"，这里 n 指用例数
        # 用同一公式，但把比例换成均值的标准误
        from .stats import Z80, Z95

        return (Z95 + Z80) * self.se(k) * (2 ** 0.5)

    def relative_gain(self, k: int) -> float:
        """相对 k=1，可测下限缩小到原来的几分之几。"""
        base = self.floor(1)
        return self.floor(k) / base if base else 1.0


def decompose(per_case: list[list[bool]]) -> Decomposition:
    """``per_case[i]`` 是第 i 条用例的 k 次观测。"""
    per_case = [row for row in per_case if row]
    if not per_case:
        return Decomposition(0, 0, 0.0, 0.0, 0.0)

    k = max(len(row) for row in per_case)
    means = [sum(row) / len(row) for row in per_case]
    grand = sum(means) / len(means)

    n = len(means)
    if n > 1:
        between = sum((m - grand) ** 2 for m in means) / (n - 1)
    else:
        between = 0.0

    within_values = []
    for row in per_case:
        if len(row) < 2:
            continue
        m = sum(row) / len(row)
        within_values.append(sum((x - m) ** 2 for x in row) / (len(row) - 1))
    within = sum(within_values) / len(within_values) if within_values else 0.0

    return Decomposition(
        cases=len(per_case), samples=k, between=between, within=within, mean=grand
    )
