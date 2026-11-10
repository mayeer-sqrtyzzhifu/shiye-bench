"""把变形测试搬进 pytest：指标一旦变成死的，这里会先红。

对应脚本是 run_metamorphic.py，两者共用同一组变形定义。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import run_metamorphic as mm  # noqa: E402


def test_baseline_is_clean():
    """基线必须没有任何问题，否则后面"上升"的结论不成立。"""
    assert mm.metrics_of(mm.BASE_REPLIES) == {}


def test_every_transform_moves_its_metric():
    baseline = mm.metrics_of(mm.BASE_REPLIES)
    for case in mm.CASES:
        before = baseline.get(case.expect, 0)
        after = mm.metrics_of(
            case.transform(mm.BASE_REPLIES), crisis=case.crisis
        ).get(case.expect, 0)
        assert after > before, f"{case.name} 没有让 {case.expect} 上升（指标可能是死的）"


def test_duplicate_transform_really_creates_adjacent_repeats():
    """第一版变形写成 replies + replies，相邻对根本不重复。"""
    doubled = mm._duplicate(["甲乙丙丁", "戊己庚辛"])
    assert doubled[0] == doubled[1]
    assert doubled[2] == doubled[3]
    assert doubled[1] != doubled[2]
