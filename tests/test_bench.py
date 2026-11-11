"""总入口验收门的测试：门本身必须会拦。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench import gate  # noqa: E402



class TestGate:
    def _ok(self):
        return {
            "crisis": {"passed": 5, "cases": 5, "infra_failures": 0},
            "memory": {"hits": 25, "cases": 32, "fabrications": 0},
            "metamorphic": {"passed": True},
            "single": {"cases": 240, "finding_count": 5},
        }

    def test_clean_run_passes(self):
        assert gate(self._ok()) == []

    def test_crisis_miss_fails(self):
        data = self._ok()
        data["crisis"]["passed"] = 4
        assert any("危机" in p for p in gate(data))

    def test_any_fabrication_fails(self):
        data = self._ok()
        data["memory"]["fabrications"] = 1
        assert any("编造" in p for p in gate(data))

    def test_dead_metric_fails(self):
        data = self._ok()
        data["metamorphic"]["passed"] = False
        assert any("变形" in p for p in gate(data))

    def test_infra_failures_fail(self):
        data = self._ok()
        data["crisis"]["infra_failures"] = 2
        assert any("生成失败" in p for p in gate(data))

    def test_low_memory_hits_fails(self):
        data = self._ok()
        data["memory"]["hits"] = 3
        assert any("命中过低" in p for p in gate(data))


class TestFailureIsolation:
    """空采样不能折成 0 —— 越低越好的指标会把故障伪装成改善。"""

    def test_ablation_returns_none_for_empty(self):
        from run_ablation import per_case_rates

        assert per_case_rates([[]], lambda t: True) == [None]
        assert per_case_rates([["a"]], lambda t: True) == [1.0]

    def test_persona_ablation_returns_none_for_empty(self):
        from run_persona_ablation import rates

        assert rates([[]], lambda t: True) == [None]
        out = rates([["a", "b"]], lambda t: True)
        assert out == [1.0]

    def test_audit_flags_are_keyed_by_case_id(self):
        from run_metrics_audit import per_case_flags

        payload = {"cases": [
            {"id": "a", "ok": True, "reply": "嗯。"},
            {"id": "b", "ok": False, "reply": ""},
            {"id": "c", "ok": True, "reply": "被这么一挡，是挺堵的。"},
        ]}
        flags = per_case_flags(payload)
        assert set(flags) == {"a", "c"}, "失败用例不应进 flags，且必须按 id 索引"


class TestLabelOrder:
    """报告里的左右标签写反过一次，导致一条结论看起来整个反转。"""

    def test_pairs_store_right_then_left(self):
        import inspect

        from run_persona_ablation import main  # noqa: F401

        src = inspect.getsource(main)
        assert 'pairs = [(r, l) for r, l in zip(right, left)' in src
        assert '"left": sum(l for _, l in pairs)' in src
        assert '"right": sum(r for r, _ in pairs)' in src


class TestRunRecords:
    """每次下结论的运行都要能独立复核：逐条回复 + 版本/配置指纹。"""

    def test_fingerprint_is_stable_and_short(self):
        from checks.result_io import fingerprint

        assert fingerprint("abc") == fingerprint("abc")
        assert fingerprint("abc") != fingerprint("abd")
        assert len(fingerprint("abc")) == 12

    def test_run_meta_has_version_and_time(self):
        from checks.result_io import run_meta

        meta = run_meta(None, cases=8, samples=1)
        assert meta["generated_at"]
        assert meta["shiye_rev"]
        assert meta["cases"] == 8

    def test_ablation_json_has_rows_and_meta(self, tmp_path):
        """消融产物必须带 rows（逐条回复）与 meta（版本指纹）。"""
        import json
        from pathlib import Path

        runs = sorted(Path("data/runs").glob("ablation-*.json"))
        if not runs:
            return  # 还没跑过就跳过
        payload = json.loads(runs[-1].read_text(encoding="utf-8"))
        assert "rows" in payload and payload["rows"]
        assert "meta" in payload and payload["meta"]["generated_at"]
        row = payload["rows"][0]
        assert "with_hint" in row and "without_hint" in row
