"""整版人格对照：同一批用例，两版人格各跑一遍，**按用例配对**比较。

和 ``run_ablation.py`` 的区别：消融切的是一个运行时提示，这里切的是**整份人格**。
用来回答 F4：把「问句至多一半」改成「默认不提问」，问句率到底降了没有。

人格文本从 ``shiye/personas/`` 取（单一事实来源），不改动主项目代码。

用法::

    python run_persona_ablation.py --left v5_nolife --right current --cases 240
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(ROOT))

from checks.result_io import fingerprint, run_meta, write_result  # noqa: E402
from checks.rules import analyze_turn, two_part_template  # noqa: E402
from checks.stats import sign_test  # noqa: E402
from runners.shiye_lib import ShiyeRunner, _ensure_shiye_on_path  # noqa: E402

CASES = ROOT / "data" / "cases" / "single_turn.jsonl"
REPORTS = ROOT / "reports"
RUNS = ROOT / "data" / "runs"

METRICS = {
    "带问句": lambda text: analyze_turn(text).strategy == "提问",
    "二段式": lambda text: two_part_template(text),
    "超长": lambda text: analyze_turn(text).length > 80,
}


def persona_text(name: str) -> str:
    """``current`` 取主项目当前的 persona；其余从 personas/ 快照加载。"""
    _ensure_shiye_on_path()
    if name == "current":
        from companion.persona import DEFAULT_PERSONA

        return DEFAULT_PERSONA.render()

    path = Path(ROOT).parent / "shiye" / "personas" / f"{name}.py"
    if not path.exists():
        raise SystemExit(f"找不到人格快照：{path}")
    module_name = f"persona_ablation_{name}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.DEFAULT_PERSONA.render()


def load_cases(limit: int) -> list[str]:
    items = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [i["user"] for i in items[:limit]]


def generate(users: list[str], text: str, *, samples: int, workers: int) -> list[list[str]]:
    def one(index: int) -> list[str]:
        out: list[str] = []
        for _ in range(samples):
            runner = ShiyeRunner(persona_text=text, with_extraction=False)
            reply = runner.converse([users[index]], case_index=index)[0]
            if reply.ok and reply.text:
                out.append(reply.text)
        return out

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(one, range(len(users))))
    return [one(i) for i in range(len(users))]


def rates(draws: list[list[str]], metric) -> list[float | None]:
    """空采样返回 None，不能折成 0（越低越好的指标会把故障当成改善）。"""
    return [
        (sum(1 for t in texts if metric(t)) / len(texts)) if texts else None
        for texts in draws
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--left", default="v5_nolife")
    parser.add_argument("--right", default="current")
    parser.add_argument("--cases", type=int, default=240)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args(argv)

    users = load_cases(args.cases)
    arms: dict[str, list[list[str]]] = {}
    texts: dict[str, str] = {}
    for side in ("left", "right"):
        name = getattr(args, side)
        texts[name] = persona_text(name)
        started = time.time()
        arms[side] = generate(users, texts[name], samples=args.samples, workers=args.workers)
        print(f"{name}：{len(users)} 条 × {args.samples} 次，用时 {time.time() - started:.0f} 秒")

    report: dict[str, dict] = {}
    for name, metric in METRICS.items():
        left = rates(arms["left"], metric)
        right = rates(arms["right"], metric)
        # 注意顺序：pairs 里第一个是 right、第二个是 left。
        # 之前把 sum(a) 写进了 "left"，报告的左右整体互换过一次。
        pairs = [(r, l) for r, l in zip(right, left) if r is not None and l is not None]
        lower = sum(1 for r, l in pairs if r < l)
        higher = sum(1 for r, l in pairs if r > l)
        if len(pairs) < 0.8 * len(right):
            print(f"  {name}: 有效配对只有 {len(pairs)}/{len(right)}，实验作废")
        report[name] = {
            "left": sum(l for _, l in pairs) / max(1, len(pairs)),
            "right": sum(r for r, _ in pairs) / max(1, len(pairs)),
            "dropped": len(right) - len(pairs),
            "lower": lower,
            "higher": higher,
            "p": sign_test(lower, higher),
        }

    left_len = [sum(analyze_turn(t).length for t in d) / len(d) if d else None for d in arms["left"]]
    right_len = [sum(analyze_turn(t).length for t in d) / len(d) if d else None for d in arms["right"]]
    len_pairs = [
        (r, l) for r, l in zip(right_len, left_len) if r is not None and l is not None
    ]
    left_len = [l for _, l in len_pairs]
    right_len = [r for r, _ in len_pairs]
    shorter = sum(1 for a, b in zip(right_len, left_len) if a < b)
    longer = sum(1 for a, b in zip(right_len, left_len) if a > b)
    report["平均长度"] = {
        "left": sum(left_len) / len(left_len),
        "right": sum(right_len) / len(right_len),
        "lower": shorter,
        "higher": longer,
        "p": sign_test(shorter, longer),
    }

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = REPORTS / f"persona-ablation-{args.left}-vs-{args.right}-{stamp}.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = [f"# 整版人格对照：{args.left} vs {args.right}\n"]
    lines.append(f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}")
    lines.append(f"- 用例 {len(users)} 条，每条 {args.samples} 次采样，并发 {args.workers}")
    lines.append(f"- 左边「{args.left}」{len(texts[args.left])} 字｜"
                 f"右边「{args.right}」{len(texts[args.right])} 字\n")
    lines.append(f"| 指标 | {args.left} | {args.right} | 差 | 更低用例 | 更高用例 | 符号检验 p |")
    lines.append("|---|---|---|---|---|---|---|")
    for name, row in report.items():
        if name == "平均长度":
            lines.append(
                f"| {name} | {row['left']:.1f} 字 | {row['right']:.1f} 字 | "
                f"{row['right'] - row['left']:+.1f} | {row['lower']} | {row['higher']} | {row['p']:.3f} |"
            )
        else:
            lines.append(
                f"| {name} | {row['left']:.1%} | {row['right']:.1%} | "
                f"{row['right'] - row['left']:+.1%} | {row['lower']} | {row['higher']} | {row['p']:.3f} |"
            )

    lines.append("\n## 结论\n")
    for name, row in report.items():
        unit = "字" if name == "平均长度" else "%"
        fmt = (lambda v: f"{v:.1f}") if name == "平均长度" else (lambda v: f"{v:.1%}")
        if row["p"] < 0.05 and row["right"] < row["left"]:
            verdict = f"**{args.right} 显著更低**（p={row['p']:.3f}）"
        elif row["p"] < 0.05:
            verdict = f"**{args.right} 显著更高**（p={row['p']:.3f}）"
        else:
            verdict = f"分不出（p={row['p']:.3f}，低 {row['lower']} / 高 {row['higher']}）"
        lines.append(f"- {name}：{fmt(row['left'])} → {fmt(row['right'])}，{verdict}")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rows = []
    for i, user in enumerate(users):
        rows.append({
            "id": f"case-{i}",
            "user": user,
            "left": arms["left"][i],
            "right": arms["right"][i],
        })
    (RUNS / f"persona-ablation-{stamp}.json").write_text(
        json.dumps({
            "meta": run_meta(
                provider,
                left=args.left, right=args.right,
                left_sha=fingerprint(texts[args.left]),
                right_sha=fingerprint(texts[args.right]),
                cases=len(users), samples=args.samples, workers=args.workers,
            ),
            "report": report,
            "rows": rows,
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    write_result("persona_ablation", {
        "left": args.left, "right": args.right,
        "metrics": {k: {"left": round(v["left"], 3), "right": round(v["right"], 3),
                        "p": round(v["p"], 4)} for k, v in report.items()},
    }, provider="real")
    print(f"报告 -> {out.relative_to(ROOT)}")
    for name, row in report.items():
        print(f"  {name}: {args.left} {row['left']:.3f} vs {args.right} {row['right']:.3f}"
              f"（低 {row['lower']} / 高 {row['higher']}，p={row['p']:.3f}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
