"""消融对照：同一版本、同一批用例，只切换一个运行时提示。

这是 F4/F5 那两条「已修未验证」唯一能验的方式——
跟历史运行比不可比：模型版本、用例集、并发方式都变过。

设计要点：

* **同一天、同一批用例、同一个并发配置**，只改 ``SHIYE_ABLATE``
* 每条用例采 k 次，得到**用例级比例**，配对比较（同一用例的两个条件）
* 用符号检验看「有多少用例变好、多少变差」，而不是比两个汇总比例

用法::

    python run_ablation.py --hint opener --cases 240 --samples 3 --workers 16
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

from checks.result_io import fingerprint, run_meta, write_result  # noqa: E402
from checks.rules import analyze_turn, two_part_template  # noqa: E402
from checks.stats import sign_test, wilson  # noqa: E402
from runners.shiye_lib import ShiyeRunner  # noqa: E402

CASES = ROOT / "data" / "cases" / "single_turn.jsonl"
REPORTS = ROOT / "reports"
RUNS = ROOT / "data" / "runs"

METRICS = {
    "二段式": lambda text: two_part_template(text),
    "带问句": lambda text: analyze_turn(text).strategy == "提问",
    "超长": lambda text: analyze_turn(text).length > 80,
}


def load_cases(limit: int) -> list[str]:
    items = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [i["user"] for i in items[:limit]]


def generate(users: list[str], *, samples: int, workers: int) -> list[list[str]]:
    """每条用例采 samples 次，返回「用例 -> 回复列表」。"""

    def one(index: int) -> list[str]:
        texts: list[str] = []
        for _ in range(samples):
            runner = ShiyeRunner(with_extraction=False)
            reply = runner.converse([users[index]], case_index=index)[0]
            if reply.ok and reply.text:
                texts.append(reply.text)
        return texts

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(one, range(len(users))))
    return [one(i) for i in range(len(users))]


def per_case_rates(draws: list[list[str]], metric) -> list[float | None]:
    """空采样返回 None —— **不能折成 0**。

    二段式、带问句、超长、长度都是"越低越好"，
    把失败算成 0 等于让基础设施故障伪装成产品改善。
    """
    rates: list[float | None] = []
    for texts in draws:
        if not texts:
            rates.append(None)
            continue
        hits = sum(1 for t in texts if metric(t))
        rates.append(hits / len(texts))
    return rates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hint", default="opener", choices=("opener", "long_input"))
    parser.add_argument("--cases", type=int, default=240)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args(argv)

    users = load_cases(args.cases)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    arms: dict[str, list[list[str]]] = {}
    timings: dict[str, float] = {}
    for label, ablate in (("有提示", ""), ("无提示", args.hint)):
        os.environ["SHIYE_ABLATE"] = ablate
        started = time.time()
        arms[label] = generate(users, samples=args.samples, workers=args.workers)
        timings[label] = time.time() - started
        print(f"{label}：{len(users)} 条 × {args.samples} 次，用时 {timings[label]:.0f} 秒")
    os.environ.pop("SHIYE_ABLATE", None)

    # 长度是连续量，单独做配对比较
    length_with = [
        sum(analyze_turn(t).length for t in texts) / len(texts) if texts else None
        for texts in arms["有提示"]
    ]
    length_without = [
        sum(analyze_turn(t).length for t in texts) / len(texts) if texts else None
        for texts in arms["无提示"]
    ]
    len_pairs = [
        (a, b) for a, b in zip(length_with, length_without)
        if a is not None and b is not None
    ]
    shorter = sum(1 for a, b in len_pairs if a < b)
    longer = sum(1 for a, b in len_pairs if a > b)
    length_report = {
        "with": sum(b for _, b in len_pairs) / max(1, len(len_pairs)),
        "without": sum(a for a, _ in len_pairs) / max(1, len(len_pairs)),
        "shorter": shorter,
        "longer": longer,
        "p": sign_test(shorter, longer),
    }

    report: dict[str, dict] = {}
    for name, metric in METRICS.items():
        with_hint = per_case_rates(arms["有提示"], metric)
        without = per_case_rates(arms["无提示"], metric)
        pairs = [
            (a, b) for a, b in zip(with_hint, without)
            if a is not None and b is not None
        ]
        dropped = len(with_hint) - len(pairs)
        if len(pairs) < 0.8 * len(with_hint):
            print(f"  {name}: 有效配对只有 {len(pairs)}/{len(with_hint)}，实验作废")
        better = sum(1 for a, b in pairs if a < b)   # 有提示更少 → 更好
        worse = sum(1 for a, b in pairs if a > b)
        p = sign_test(better, worse)
        report[name] = {
            "with": sum(a for a, _ in pairs) / max(1, len(pairs)),
            "without": sum(b for _, b in pairs) / max(1, len(pairs)),
            "dropped": dropped,
            "better": better,
            "worse": worse,
            "p": p,
        }

    report["平均长度"] = length_report

    out = REPORTS / f"ablation-{args.hint}-{stamp}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# 消融对照：{args.hint} 提示\n"]
    lines.append(f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}")
    lines.append(f"- 用例 {len(users)} 条，每条 {args.samples} 次采样，并发 {args.workers}")
    lines.append(f"- 两臂在同一天、同一用例集、同一配置下跑（只切 `SHIYE_ABLATE`）\n")
    lines.append("| 指标 | 有提示 | 无提示 | 差 | 变好用例 | 变差用例 | 符号检验 p |")
    lines.append("|---|---|---|---|---|---|---|")
    for name, row in report.items():
        if name == "平均长度":
            lines.append(
                f"| {name} | {row['with']:.1f} 字 | {row['without']:.1f} 字 | "
                f"{row['with'] - row['without']:+.1f} | {row['shorter']} | "
                f"{row['longer']} | {row['p']:.3f} |"
            )
        else:
            lines.append(
                f"| {name} | {row['with']:.1%} | {row['without']:.1%} | "
                f"{row['with'] - row['without']:+.1%} | {row['better']} | {row['worse']} | "
                f"{row['p']:.3f} |"
            )

    lines.append("\n## 怎么读\n")
    lines.append("- 「变好用例 / 变差用例」是**配对**比较：同一用例在两个条件下的比例谁低")
    lines.append("- 只看汇总比例会被用例难易带偏，所以主判据是符号检验")
    lines.append("- p < 0.05 才算这个提示**在所有用例上**有稳定作用\n")
    for name, row in report.items():
        if name == "平均长度":
            verdict = "有效" if row["p"] < 0.05 and row["with"] < row["without"] else "分不出"
            lines.append(f"- 平均长度：{verdict}（p={row['p']:.3f}，"
                         f"短 {row['shorter']} / 长 {row['longer']}）")
            continue
        if row["p"] < 0.05 and row["with"] < row["without"]:
            lines.append(f"- **{name}**：提示有效（p={row['p']:.3f}，{row['better']} 好 / {row['worse']} 坏）")
        elif row["p"] < 0.05:
            lines.append(f"- **{name}**：提示**有害**（p={row['p']:.3f}）")
        else:
            lines.append(f"- {name}：分不出（p={row['p']:.3f}，{row['better']} 好 / {row['worse']} 坏）")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rows = [
        {"id": f"case-{i}", "user": user,
         "with_hint": arms["有提示"][i], "without_hint": arms["无提示"][i]}
        for i, user in enumerate(users)
    ]
    (RUNS / f"ablation-{args.hint}-{stamp}.json").write_text(
        json.dumps({
            # 这个脚本不直接用 provider 对象，模型信息从环境无法得知，
            # 只记版本与配置指纹
            "meta": run_meta(None, hint=args.hint, cases=len(users),
                             samples=args.samples, workers=args.workers),
            "report": report,
            "rows": rows,
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    lines.append(
        f"- 长度：有提示 {length_report['with']:.1f} 字 vs 无提示 "
        f"{length_report['without']:.1f} 字（p={length_report['p']:.3f}）"
    )
    write_result("ablation", {
        "hint": args.hint,
        "metrics": {
            k: {"with": round(v["with"], 3), "without": round(v["without"], 3),
                "p": round(v["p"], 4)}
            for k, v in report.items()
        },
        "length": {"with": round(length_report["with"], 1),
                   "without": round(length_report["without"], 1),
                   "p": round(length_report["p"], 4)},
    }, provider="real")
    print(f"报告 -> {out.relative_to(ROOT)}")
    for name, row in report.items():
        if "better" in row:
            print(f"  {name}: 有 {row['with']:.1%} vs 无 {row['without']:.1%}"
                  f"（好 {row['better']} / 坏 {row['worse']}，p={row['p']:.3f}）")
        else:
            print(f"  {name}: 有 {row['with']:.1f} vs 无 {row['without']:.1f}"
                  f"（短 {row['shorter']} / 长 {row['longer']}，p={row['p']:.3f}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
