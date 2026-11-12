"""跑跨天记忆评测。

场景：第 0 天埋点，隔 1~3 天探测。看 agent 记不记得、会不会编、不记得时诚不诚实。

用法::

    python run_memory.py --provider real
    python run_memory.py --provider fake
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(ROOT))

from checks.memory import check_memory  # noqa: E402
from checks.result_io import write_result  # noqa: E402
from runners.shiye_lib import ShiyeRunner, fake_provider, shiye_rev  # noqa: E402

CASES = ROOT / "cases" / "memory.json"
REPORTS = ROOT / "reports"
RUNS = ROOT / "data" / "runs"

# 假 provider：单条回复会被每一轮复用（FakeProvider 用完剧本就停最后一条），
# 所以这里必须只放一条——否则埋点轮会把剧本消耗掉，探测轮拿到不相干的句子。
FAKE_REMEMBER = ["嗯，团子，记得。"]
FAKE_FABRICATE = ["记得啊，你家那只狗挺可爱的。"]
FAKE_ABSTAIN = ["我这儿没存下那段，不记得了。"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("fake", "fabricate", "abstain", "real"), default="fake")
    parser.add_argument("--forget", action="store_true",
                        help="埋点之后清空记忆库 —— 命中率必须掉到 0，否则说明命中不是来自记忆")
    args = parser.parse_args(argv)

    def make_runner():
        if args.provider == "fake":
            return ShiyeRunner(provider=fake_provider(FAKE_REMEMBER))
        if args.provider == "fabricate":
            return ShiyeRunner(provider=fake_provider(FAKE_FABRICATE))
        if args.provider == "abstain":
            return ShiyeRunner(provider=fake_provider(FAKE_ABSTAIN))
        return ShiyeRunner()

    payload = json.loads(CASES.read_text(encoding="utf-8"))
    cases = payload["cases"]

    rows = []
    for index, case in enumerate(cases):
        runner = make_runner()
        conn = runner.open_case(index)
        try:
            plant_turns = [p["text"] for p in case["plant"]]
            plant_offsets = [p["day"] for p in case["plant"]]
            plant_replies = runner.converse(
                plant_turns, case_index=index, conn=conn, day_offsets=plant_offsets
            )
            if args.forget:
                # 变形：把记忆库清空，但保留会话本身
                conn.execute("DELETE FROM memory_items")
                conn.execute("DELETE FROM messages")
                conn.execute("DELETE FROM messages_fts")
                conn.execute("DELETE FROM memories_fts")
                conn.commit()
            probe_reply = runner.converse(
                [case["probe"]["text"]], case_index=index, conn=conn,
                day_offsets=[case["probe"]["day"]],
            )[-1]
            replies = plant_replies + [probe_reply]
        finally:
            conn.close()
        verdict = check_memory(
            probe_reply.text,
            expect=case["expect"],
            forbid=case["forbid"],
        ) if probe_reply.ok else None
        # 没说过的事：正确行为是诚实弃答，而不是命中。
        # 判定统一走 passed()，不再改写 verdict.hit —— 改写会掩盖编造。
        abstain_expected = bool(case.get("expect_abstain"))
        rows.append({"case": case, "replies": replies, "verdict": verdict})

    ok_rows = [r for r in rows if r["verdict"]]
    hits = sum(
        1 for r in ok_rows
        if r["verdict"].passed(expect_abstain=bool(r["case"].get("expect_abstain")))
    )
    fabrications = sum(1 for r in ok_rows if r["verdict"].fabricated)
    abstains = sum(1 for r in ok_rows if r["verdict"].abstained and not r["verdict"].hit)
    by_ref = sum(1 for r in ok_rows if r["verdict"].understood_by_reference)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    RUNS.mkdir(parents=True, exist_ok=True)
    run_file = RUNS / f"memory-{args.provider}-{stamp}.json"
    run_file.write_text(json.dumps({
        "provider": args.provider,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "shiye_rev": shiye_rev(),
        "cases": [
            {"id": r["case"]["id"], "turns": [p["text"] for p in r["case"]["plant"]] + [r["case"]["probe"]["text"]],
             "replies": [x.text for x in r["replies"]]}
            for r in rows
        ],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    out = REPORTS / f"memory-{args.provider}-{stamp}.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = [f"# 跨天记忆评测（{args.provider}）\n"]
    lines.append(f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}")
    lines.append(f"- 用例数：{len(cases)}｜成功回复：{len(ok_rows)}\n")
    lines.append("## 汇总\n")
    lines.append("| 指标 | 值 | 方向 |")
    lines.append("|---|---|---|")
    lines.append(f"| 命中率 | {hits}/{len(ok_rows) or 1} | 越高越好 |")
    lines.append(f"| 编造 | {fabrications} | 越低越好 |")
    lines.append(f"| 指代理解 | {by_ref} | 接上了但没复述 |")
    lines.append(f"| 诚实弃答 | {abstains} | 未命中时该出现 |")
    lines.append("")
    lines.append("## 逐条\n")
    lines.append("| 用例 | 埋点 | 探测 | 回复 | 判定 |")
    lines.append("|---|---|---|---|---|")
    for row in rows:
        case = row["case"]
        probe = case["probe"]["text"].replace("|", "｜")
        reply = row["replies"][-1]
        text = (reply.text or "⚠️ " + str(reply.notes)).replace("|", "｜").replace("\n", " ")
        verdict = row["verdict"].summary() if row["verdict"] else "失败"
        lines.append(f"| {case['id']} | {len(case['plant'])} 轮 | {probe} | {text} | {verdict} |")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"原始 -> {run_file.relative_to(ROOT)}")
    write_result("memory", {
        "cases": len(ok_rows),
        "hits": hits,
        "by_reference": by_ref,
        "fabrications": fabrications,
        "abstains": abstains,
        "forget": args.forget,
    }, provider=args.provider)
    print(f"报告 -> {out.relative_to(ROOT)}")
    print(f"命中 {hits}/{len(ok_rows)}｜指代理解 {by_ref}｜编造 {fabrications}｜诚实弃答 {abstains}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
