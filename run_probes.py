"""定向探针：直接问 agent 自己的生活，测它会不会编。

为什么单独一套：p5 那版人格就是为了解决"agent 聊自己的猫和饭"才去掉生活细节的，
但这种泄露在通用用例里是低频的（12 条命中 0 次）——不直接问，永远测不出来。

用法::

    python run_probes.py
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(ROOT))

from checks.result_io import write_result  # noqa: E402
from checks.rules import check_probe_leak  # noqa: E402
from runners.shiye_lib import ShiyeRunner  # noqa: E402

CASES = ROOT / "cases" / "persona_probe.json"
PERSONA_DIR = ROOT / "data" / "personas"
MANIFEST = PERSONA_DIR / "manifest.json"
REPORTS = ROOT / "reports"


def load_persona(name: str) -> str:
    path = PERSONA_DIR / f"{name}.py"
    module_name = f"persona_{name}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module.DEFAULT_PERSONA.render()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--personas", default=None)
    args = parser.parse_args(argv)

    if not MANIFEST.exists():
        raise SystemExit("先跑 scripts/extract_personas.py")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if args.personas:
        wanted = set(args.personas.split(","))
        manifest = [m for m in manifest if m["name"] in wanted]

    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]

    results = []
    for entry in manifest:
        runner = ShiyeRunner(persona_text=load_persona(entry["name"]), with_extraction=False)
        rows = []
        for index, case in enumerate(cases):
            replies = runner.converse([case["user"]], case_index=index)
            reply = replies[0]
            findings = check_probe_leak(reply.text, case.get("forbid", [])) if reply.ok else []
            rows.append({"case": case, "reply": reply, "findings": findings})
        results.append({"entry": entry, "rows": rows})
        hits = sum(1 for r in rows if r["findings"])
        print(f"{entry['name']:<14} 编造生活 {hits}/{len(rows)}")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    runs_dir = ROOT / "data" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"probes-{stamp}.json").write_text(json.dumps({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "personas": [
            {"name": r["entry"]["name"],
             "items": [{"user": x["case"]["user"], "reply": x["reply"].text,
                        "rule_leak": bool(x["findings"])} for x in r["rows"]]}
            for r in results
        ],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    out = REPORTS / f"probes-{stamp}.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = ["# 定向探针：agent 会不会编自己的生活\n"]
    lines.append(f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}")
    lines.append(f"- 探针数：{len(cases)}\n")
    lines.append("| 版本 | 编造次数 | 泄露率 |")
    lines.append("|---|---|---|")
    for row in results:
        hits = sum(1 for r in row["rows"] if r["findings"])
        lines.append(f"| {row['entry']['name']} | {hits}/{len(row['rows'])} | {hits / len(row['rows']):.0%} |")

    lines.append("\n## 明细\n")
    for row in results:
        lines.append(f"### {row['entry']['name']}\n")
        for item in row["rows"]:
            reply = item["reply"]
            text = (reply.text or "⚠️").replace("\n", " ")
            flag = "🚫 " + ",".join(f.detail for f in item["findings"]) if item["findings"] else ""
            lines.append(f"- 问：{item['case']['user']}")
            lines.append(f"  答：{text}  {flag}")
        lines.append("")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_result("probes", {
        "personas": len(results),
        "cases": len(cases),
        "leaks": {r["entry"]["name"]: sum(1 for x in r["rows"] if x["findings"]) for r in results},
    }, provider="personas")
    print(f"\n报告 -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
