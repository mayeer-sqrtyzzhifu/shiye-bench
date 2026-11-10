"""统一入口：一次跑完所有维度，输出总览。

用法::

    python bench.py --provider fake                # 零成本冒烟
    python bench.py --provider real                # 真实模型
    python bench.py --provider real --repeat 2     # 每维跑 2 遍取中位
    python bench.py --skip metamorphic             # 跳过某维

为什么需要它：
1. 之前要跑四个脚本、看四份报告，没办法一眼看出"这版整体怎么样"
2. 单次运行有 ±1 的波动（实测记忆维度 3/4 与 2/4 之间来回），
   跑 N 次取中位才敢说"变了"
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(ROOT))

from checks.result_io import read_result, wilson  # noqa: E402
from runners.shiye_lib import shiye_rev  # noqa: E402

REPORTS = ROOT / "reports"

DIMENSIONS = {
    "single": "单轮（长度/问句/AI 腔/语气词）",
    "arcs": "情绪弧（回落/卡带/复读/断崖）",
    "memory": "跨天记忆（命中/编造/弃答）",
    "crisis": "危机路径（资源/禁语）",
    "metamorphic": "变形测试（指标是否活着）",
    "voice": "语气度量（口语/书面密度 vs 真人）",
}


def run_single(provider: str) -> int:
    """用全部用例跑。实测 240 条能把可测下限从 23pp 压到 12pp。"""
    import run as mod

    # 并发 16：240 条从约 27 分钟压到 1.8 分钟，且没撞到限流
    return mod.main(["--provider", provider, "--limit", "240", "--workers", "16"])


def run_arcs(provider: str) -> int:
    import run_arcs as mod

    return mod.main(["--provider", provider, "--limit", "6"])


def run_memory(provider: str) -> int:
    import run_memory as mod

    return mod.main(["--provider", provider])


def run_crisis(provider: str) -> int:
    import run_crisis as mod

    return mod.main(["--provider", provider])


def run_metamorphic(provider: str) -> int:
    import run_metamorphic as mod

    return mod.main()


def run_voice(provider: str) -> int:
    import run_voice as mod

    return mod.main()


RUNNERS = {
    "voice": run_voice,
    "single": run_single,
    "arcs": run_arcs,
    "memory": run_memory,
    "crisis": run_crisis,
    "metamorphic": run_metamorphic,
}


def _median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("fake", "real"), default="fake")
    parser.add_argument("--repeat", type=int, default=1, help="每维重复次数，取中位")
    parser.add_argument(
        "--skip", default="voice",
        help="逗号分隔，跳过某些维度；默认跳过 voice（它依赖人格运行结果）",
    )
    args = parser.parse_args(argv)

    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    dims = [d for d in DIMENSIONS if d not in skip]

    collected: dict[str, list[dict]] = {d: [] for d in dims}
    for round_index in range(args.repeat):
        if args.repeat > 1:
            print(f"\n===== 第 {round_index + 1}/{args.repeat} 轮 =====")
        for dim in dims:
            print(f"\n--- {dim}：{DIMENSIONS[dim]} ---")
            code = RUNNERS[dim](args.provider)
            if dim == "metamorphic":
                collected[dim].append({"passed": code == 0})
            elif dim == "crisis":
                result = read_result("crisis") or {}
                collected[dim].append(result.get("metrics", {}))
            else:
                result = read_result(dim) or {}
                collected[dim].append(result.get("metrics", {}))

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = REPORTS / f"summary-{args.provider}-{stamp}.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = [f"# 总体结果（{args.provider} · {args.repeat} 轮）\n"]
    lines.append(f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}")
    lines.append(f"- 被测版本：shiye @ {shiye_rev()}\n")

    lines.append("## 总览\n")
    lines.append("| 维度 | 关键指标 | 值 | 方向 |")
    lines.append("|---|---|---|---|")
    for dim in dims:
        runs = collected[dim]
        if dim == "single":
            lens = [r.get("avg_length", 0) for r in runs]
            qs = [r.get("avg_questions", 0) for r in runs]
            inter = [r.get("interjection_openings", 0) for r in runs]
            finds = [r.get("finding_count", 0) for r in runs]
            two = [r.get("two_part", 0) for r in runs]
            cases = [r.get("cases", 1) for r in runs]
            lines.append(f"| 单轮 | 平均长度 | {_median(lens):.1f} | 10–80 |")
            lines.append(f"| 单轮 | 平均问句 | {_median(qs):.2f} | ≤1 |")
            lines.append(f"| 单轮 | 语气词开头 | {_median(inter):.0f} | 越少越好 |")
            lines.append(
                f"| 单轮 | 二段式（开场） | {_median(two):.0f}/{_median(cases):.0f} | 越低越好 |"
            )
            lines.append(f"| 单轮 | 规则命中 | {_median(finds):.0f} | 0 |")
        elif dim == "arcs":
            stuck = [r.get("stuck_rate", 0) for r in runs]
            rep = [r.get("repeat_rate", 0) for r in runs]
            jump = [r.get("jump_rate", 0) for r in runs]
            rel = [r.get("peak_relief", 0) for r in runs]
            elig = [r.get("relief_eligible", 0) for r in runs]
            if _median(elig):
                lo, hi = wilson(int(_median(rel)), int(_median(elig)))
                ci = f"（95% CI {lo:.0%}–{hi:.0%}）"
            else:
                ci = "（无可判断样本）"
            lines.append(
                f"| 弧 | 峰值后回落 | {_median(rel):.0f}/{_median(elig):.0f}{ci} | 越高越好 |"
            )
            lines.append(f"| 弧 | 卡带率 | {_median(stuck):.0%} | 0 |")
            lines.append(f"| 弧 | 复读率 | {_median(rep):.0%} | 0 |")
            lines.append(f"| 弧 | 断崖率 | {_median(jump):.0%} | 0 |")
        elif dim == "memory":
            hits = [r.get("hits", 0) for r in runs]
            fab = [r.get("fabrications", 0) for r in runs]
            abst = [r.get("abstains", 0) for r in runs]
            cases = [r.get("cases", 4) for r in runs]
            lo, hi = wilson(int(_median(hits)), int(_median(cases)))
            lines.append(
                f"| 记忆 | 命中 | {_median(hits):.0f}/{_median(cases):.0f}"
                f"（95% CI {lo:.0%}–{hi:.0%}） | 越高越好 |"
            )
            lines.append(f"| 记忆 | 编造 | {_median(fab):.0f} | 0 |")
            lines.append(f"| 记忆 | 诚实弃答 | {_median(abst):.0f} | 未命中时该有 |")
        elif dim == "crisis":
            passed = [r.get("passed", 0) for r in runs]
            total = [r.get("cases", 5) for r in runs]
            lo, hi = wilson(int(_median(passed)), int(_median(total)))
            lines.append(
                f"| 危机 | 通过 | {_median(passed):.0f}/{_median(total):.0f}"
                f"（95% CI {lo:.0%}–{hi:.0%}） | 满分为准 |"
            )
        elif dim == "metamorphic":
            ok = sum(1 for r in runs if r.get("passed"))
            lines.append(f"| 变形 | 全部通过 | {ok}/{len(runs)} | 必须全过 |")
        elif dim == "voice":
            result = read_result("voice") or {}
            metrics = result.get("metrics", {})
            for name, dist in metrics.items():
                lines.append(f"| 语气 | {name} 离咨询师 | {dist:.2f} | 越小越像人 |")

    if args.repeat > 1:
        lines.append("\n## 波动与可区分性\n")
        lines.append("> 样本只有 4–12 个时，二项比例的 95% 区间很宽。"
                     "两轮的区间重叠 = **分不出差别**，别当成退化或进步。\n")
        lines.append("| 维度 | 每轮原始值 |")
        lines.append("|---|---|")
        for dim in dims:
            if dim in ("metamorphic",):
                continue
            raw = [json.dumps(r, ensure_ascii=False) for r in collected[dim]]
            lines.append(f"| {dim} | {' ／ '.join(raw)} |")

        # 对"k/n"型指标给出可区分性判断
        def _binary(dim: str, key: str, denom_key: str) -> str:
            vals = [(int(r.get(key, 0)), int(r.get(denom_key, 0))) for r in collected[dim]]
            if any(total == 0 for _, total in vals):
                return "样本为空，无法判断"
            if len(set(vals)) == 1:
                return "两轮相同"
            intervals = [wilson(a, b) for a, b in vals]
            lo = max(i[0] for i in intervals)
            hi = min(i[1] for i in intervals)
            if lo > hi:
                return "可区分"
            return f"区间重叠（{lo:.0%}–{hi:.0%}），分不出差别"

        lines.append("\n## 可区分性\n")
        lines.append("| 指标 | 结论 |")
        lines.append("|---|---|")
        lines.append(f"| 记忆命中 | {_binary('memory', 'hits', 'cases')} |")
        lines.append(f"| 危机通过 | {_binary('crisis', 'passed', 'cases')} |")
        lines.append(f"| 弧·峰值回落 | {_binary('arcs', 'peak_relief', 'relief_eligible')} |")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n总览 -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
