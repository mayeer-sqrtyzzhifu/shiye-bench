"""记忆的配对消融：指代兜底到底有没有用。

F2 当初的证据是「2/4 → 3/4」——**n=4**，比任何一条产品发现都弱。
这轮用和大样本同一套规矩重做：

* 同一批 10 条记忆用例
* 每条跑 k 次（每次全新库）
* 两臂只差一个开关：``SHIYE_ABLATE=anaphoric``
* 按用例配对做符号检验

单条用例的判定是「命中 / 未命中」，k 次得到比例，配对比较。

用法::

    python run_memory_ablation.py --samples 5 --workers 8
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(ROOT))

from checks.memory import check_memory  # noqa: E402
from checks.result_io import write_result  # noqa: E402
from checks.stats import sign_test  # noqa: E402
from runners.shiye_lib import ShiyeRunner  # noqa: E402

CASES = ROOT / "cases" / "memory.json"
REPORTS = ROOT / "reports"
RUNS = ROOT / "data" / "runs"


def passed(verdict, *, expect_abstain: bool = False) -> bool:
    """统一判定。**下游一律用这个，不要只看 verdict.hit。**

    只看 hit 会把「周五和周三都记得」这种同时说出新旧值的回复算成命中。
    """
    if verdict.fabricated:
        return False
    if expect_abstain:
        return verdict.abstained and not verdict.hit
    return verdict.hit


def load_cases() -> list[dict]:
    return json.loads(CASES.read_text(encoding="utf-8"))["cases"]


def run_case(case: dict, index: int) -> tuple[bool | None, str]:
    """跑一条用例，返回（是否命中，探针回复）。"""
    runner = ShiyeRunner(with_extraction=True)
    conn = runner.open_case(index)
    try:
        plant = [p["text"] for p in case["plant"]]
        offsets = [p["day"] for p in case["plant"]]
        runner.converse(plant, case_index=index, conn=conn, day_offsets=offsets)
        reply = runner.converse(
            [case["probe"]["text"]], case_index=index, conn=conn,
            day_offsets=[case["probe"]["day"]],
        )[-1]
    finally:
        conn.close()

    if not reply.ok:
        return None, ""
    verdict = check_memory(reply.text, expect=case["expect"], forbid=case["forbid"])
    return passed(verdict, expect_abstain=bool(case.get("expect_abstain"))), reply.text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument(
        "--compare", default="anaphoric",
        help="要关掉的机制：anaphoric（指代兜底）或 hedge（不确定标注）",
    )
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)

    cases = load_cases()
    arms: dict[str, list[list[bool]]] = {}
    samples_text: dict[str, list[str]] = {}

    if args.compare == "hedge":
        labels = ("有标注", "无标注")
    else:
        labels = ("有兜底", "无兜底")
    for label, ablate in zip(labels, ("", args.compare)):
        os.environ["SHIYE_ABLATE"] = ablate
        started = time.time()
        rows: list[list[bool]] = [[] for _ in cases]
        texts: list[str] = []
        jobs = [(ci, k) for ci in range(len(cases)) for k in range(args.samples)]

        def one(job):
            ci, k = job
            ok, text = run_case(cases[ci], ci * 1000 + k)
            return ci, ok, text

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for ci, ok, text in pool.map(one, jobs):
                if ok is not None:
                    rows[ci].append(ok)
                if text:
                    texts.append(text)
        arms[label] = rows
        samples_text[label] = texts
        print(f"{label}：{len(cases)} 条 × {args.samples} 次，用时 {time.time() - started:.0f} 秒")
    os.environ.pop("SHIYE_ABLATE", None)

    with_fb = [sum(r) / len(r) if r else 0.0 for r in arms[labels[0]]]
    without = [sum(r) / len(r) if r else 0.0 for r in arms[labels[1]]]
    better = sum(1 for a, b in zip(with_fb, without) if a > b)
    worse = sum(1 for a, b in zip(with_fb, without) if a < b)
    p_value = sign_test(better, worse)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = REPORTS / f"memory-ablation-{stamp}.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = ["# 记忆消融：指代兜底有没有用\n"]
    lines.append(f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}")
    lines.append(f"- 用例 {len(cases)} 条，每条 {args.samples} 次，并发 {args.workers}")
    lines.append("- 两臂只差 `SHIYE_ABLATE=anaphoric`\n")
    lines.append("| 指标 | 有兜底 | 无兜底 | 差 |")
    lines.append("|---|---|---|---|")
    lines.append(
        f"| 命中率 | {sum(with_fb)/len(with_fb):.0%} | {sum(without)/len(without):.0%} | "
        f"{(sum(with_fb)-sum(without))/len(with_fb):+.0%} |"
    )
    lines.append("")
    lines.append("## 逐条（k 次里的命中次数）\n")
    lines.append("| 用例 | 有兜底 | 无兜底 | 差 |")
    lines.append("|---|---|---|---|")
    for i, case in enumerate(cases):
        a = arms[labels[0]][i]
        b = arms[labels[1]][i]
        lines.append(
            f"| {case['id']} | {sum(a)}/{len(a)} | {sum(b)}/{len(b)} | "
            f"{sum(a)/len(a) - sum(b)/len(b):+.0%} |"
        )

    lines.append("\n## 结论\n")
    if p_value < 0.05 and better > worse:
        lines.append(f"- 兜底**有效**：{better} 条变好、{worse} 条变差（p={p_value:.3f}）")
    elif p_value < 0.05:
        lines.append(f"- 兜底**有害**：{better} 条变好、{worse} 条变差（p={p_value:.3f}）")
    else:
        lines.append(f"- 分不出：{better} 条变好、{worse} 条变差（p={p_value:.3f}）")
        lines.append("")
        lines.append("> 用例只有 10 条，符号检验的分辨力有限：")
        lines.append("> 要显著至少需要 6:0 或 0:6 这种一边倒的结果。")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (RUNS / f"memory-ablation-{stamp}.json").write_text(json.dumps({
        "samples": args.samples,
        "with": [sum(r) for r in arms[labels[0]]],
        "without": [sum(r) for r in arms[labels[1]]],
        "n_per_case": [len(r) for r in arms[labels[0]]],
        "better": better, "worse": worse, "p": p_value,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    write_result("memory_ablation", {
        "with": round(sum(with_fb) / len(with_fb), 3),
        "without": round(sum(without) / len(without), 3),
        "better": better, "worse": worse, "p": round(p_value, 4),
    }, provider="real")
    print(f"报告 -> {out.relative_to(ROOT)}")
    print(f"有兜底 {sum(with_fb)/len(with_fb):.0%} vs 无 {sum(without)/len(without):.0%}"
          f"（好 {better} / 坏 {worse}，p={p_value:.3f}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
