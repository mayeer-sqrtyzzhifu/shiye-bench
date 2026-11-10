"""语气度量的单元测试：纯统计，不联网。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from checks.voice import distance, measure, profile  # noqa: E402


class TestMeasure:
    def test_colloquial_markers_raise_orality(self):
        plain = measure("这件事确实很难办。")
        casual = measure("这事儿呀，确实挺难的嘛。")
        assert casual.orality > plain.orality

    def test_formal_connectives_raise_formality(self):
        formal = measure("因此，基于以上考虑，我们应当调整方案。")
        assert formal.formality > 0

    def test_emotional_chat_has_no_formality(self):
        assert measure("被这么一挡，是挺堵的。").formality == 0.0

    def test_question_marks_counted(self):
        assert measure("你是想说说，还是先缓缓？").question_marks > 0

    def test_ellipsis_counted(self):
        assert measure("我这儿啊……说不清。").ellipsis > 0

    def test_empty_is_safe(self):
        assert measure("").length == 0


class TestProfile:
    def test_averages_over_replies(self):
        prof = profile(["嗯。", "嗯。", "嗯。"])
        assert prof["n"] == 3
        assert prof["length"] == 2.0

    def test_empty_list(self):
        assert profile([]) == {}

    def test_blank_entries_ignored(self):
        prof = profile(["嗯。", "   ", ""])
        assert prof["n"] == 1


class TestDistance:
    def test_identical_point_is_zero(self):
        ref = [{"orality": 1.0, "formality": 0.0, "question_marks": 0.5, "ellipsis": 0.1},
               {"orality": 1.2, "formality": 0.1, "question_marks": 0.7, "ellipsis": 0.1}]
        point = {"orality": 1.1, "formality": 0.05, "question_marks": 0.6, "ellipsis": 0.1}
        assert distance(point, ref) < 0.5

    def test_outlier_is_far(self):
        ref = [{"orality": 0.1, "formality": 0.1, "question_marks": 0.1, "ellipsis": 0.1},
               {"orality": 0.2, "formality": 0.2, "question_marks": 0.2, "ellipsis": 0.1}]
        point = {"orality": 9.0, "formality": 0.1, "question_marks": 0.1, "ellipsis": 0.1}
        assert distance(point, ref) > 3

    def test_length_is_ignored(self):
        """长度不进距离 —— 陪伴型回复本来就比咨询师短得多。"""
        ref = [{"length": 100, "orality": 0.1, "formality": 0.0,
                "question_marks": 0.1, "ellipsis": 0.0},
               {"length": 120, "orality": 0.2, "formality": 0.1,
                "question_marks": 0.2, "ellipsis": 0.1}]
        point = {"length": 30, "orality": 0.15, "formality": 0.05,
                 "question_marks": 0.15, "ellipsis": 0.05}
        assert distance(point, ref) < 1.0
