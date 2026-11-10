"""统计 SmileChat 采样样本的结构特征。

关注的是"能不能当作我们用例的素材"，所以只看结构面：
轮数、长度分布、角色、标注是否可用、开场形态。

用法::

    python scripts/analyze_smilechat.py
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "smilechat"
OUT = ROOT / "docs" / "smilechat-analysis.md"


def _chars(text: str) -> int:
    return len(text.strip())


def _pct(values: list[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * q))
    return ordered[index]


def load_dialogs() -> tuple[list[list[dict]], list[str]]:
    dialogs: list[list[dict]] = []
    bad: list[str] = []
    for path in sorted(DATA_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            bad.append(path.name)
            continue
        if not isinstance(payload, list) or not payload:
            bad.append(path.name)
            continue
        if not all(isinstance(t, dict) and "role" in t and "content" in t for t in payload):
            bad.append(path.name)
            continue
        dialogs.append(payload)
    return dialogs, bad


def main() -> int:
    if not DATA_DIR.exists():
        print("还没有下载数据，先跑 scripts/fetch_smilechat.py", file=sys.stderr)
        return 2

    dialogs, bad = load_dialogs()
    if not dialogs:
        print("没有可用对话", file=sys.stderr)
        return 2

    turns_per = [len(d) for d in dialogs]
    roles = Counter(t["role"] for d in dialogs for t in d)

    by_role: dict[str, list[int]] = {}
    for dialog in dialogs:
        for turn in dialog:
            by_role.setdefault(turn["role"], []).append(_chars(turn["content"]))

    # 标注：label 是否有内容
    label_total = 0
    label_filled = 0
    for dialog in dialogs:
        for turn in dialog:
            for ann in turn.get("annotation") or []:
                label_total += 1
                if str(ann.get("label", "")).strip():
                    label_filled += 1

    # 开场形态
    first = [d[0] for d in dialogs]
    first_is_question = sum(1 for t in first if "？" in t["content"] or "?" in t["content"])
    first_len = [_chars(t["content"]) for t in first]

    all_client = by_role.get("client", [])
    all_counselor = by_role.get("counselor", [])

    lines: list[str] = []
    lines.append("# SmileChat 采样分析\n")
    lines.append(f"> 样本：{len(dialogs)} 段对话（仓库共 55,165 个文件，固定 seed 采样）\n")
    if bad:
        lines.append(f"> ⚠️ 另有 {len(bad)} 个文件无法解析：{', '.join(bad[:5])}\n")

    lines.append("## 结构\n")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 对话数 | {len(dialogs)} |")
    lines.append(f"| 总轮数 | {sum(turns_per)} |")
    lines.append(
        f"| 每段轮数 | 中位 {statistics.median(turns_per):.0f}，"
        f"最短 {min(turns_per)}，最长 {max(turns_per)} |"
    )
    lines.append(f"| 角色分布 | {dict(roles)} |")
    lines.append("")

    lines.append("## 长度（字符数）\n")
    lines.append("| 角色 | 条数 | 中位 | P90 | 最短 | 最长 |")
    lines.append("|---|---|---|---|---|---|")
    for role, values in sorted(by_role.items()):
        lines.append(
            f"| {role} | {len(values)} | {statistics.median(values):.0f} | "
            f"{_pct(values, 0.9)} | {min(values)} | {max(values)} |"
        )
    lines.append("")

    lines.append("## 标注可用性\n")
    if label_total:
        ratio = label_filled / label_total
        lines.append(
            f"- 标注条目 {label_total} 条，其中有内容的 {label_filled} 条"
            f"（{ratio:.1%}）"
        )
        if ratio < 0.1:
            lines.append("- **结论：策略标注基本为空，不能直接当策略标签用**")
    else:
        lines.append("- 没有 annotation 字段")
    lines.append("")

    lines.append("## 开场形态\n")
    lines.append(f"- 带问号开场：{first_is_question}/{len(first)}（{first_is_question / len(first):.0%}）")
    lines.append(
        f"- 开场长度：中位 {statistics.median(first_len):.0f}，P90 {_pct(first_len, 0.9)}"
    )
    lines.append("")

    lines.append("## 对我们用例的意义\n")
    if all_counselor:
        med_c = statistics.median(all_counselor)
        med_u = statistics.median(all_client) if all_client else 0
        lines.append(
            f"- 咨询师回复中位 {med_c:.0f} 字，来访者 {med_u:.0f} 字，"
            f"比值约 {med_c / med_u:.1f}×"
        )
        if med_c > 120:
            lines.append(
                "- 咨询师回复偏长，**不适合直接当陪伴风格参照**；"
                "价值在来访者那一侧的真实表达"
            )
    lines.append(f"- 开场带问号比例 {first_is_question / len(first):.0%}，说明多为求助式开场，较少日常闲聊")

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"写出 {OUT.relative_to(ROOT)}")
    print(f"对话 {len(dialogs)}｜总轮数 {sum(turns_per)}｜角色 {dict(roles)}")
    print(f"client 中位 {statistics.median(all_client):.0f} 字｜counselor 中位 "
          f"{statistics.median(all_counselor):.0f} 字")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
