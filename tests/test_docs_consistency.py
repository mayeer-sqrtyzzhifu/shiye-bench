"""文档里的测试数量必须和实际收集数一致。

这条测试是为了止血：`shiye/README.md` 写 302 而 `HANDOFF.md` 写 322 的情况
真实发生过——同一个项目，两个文档，两个数字。

注意：加了这条测试之后总数会 +2，所以文档里的数字要跟着改。
失败信息会直接告诉你该写多少。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_COUNT = re.compile(r"(\d+)\s*项")


def _collected() -> int:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    # 两种输出都要认：有的环境给「N tests collected」，有的只给「文件: 条数」
    summary = re.search(r"(\d+)\s+tests?\s+collected", result.stdout)
    if summary:
        return int(summary.group(1))
    per_file = re.findall(r"^[^\n]*\.py: (\d+)$", result.stdout, flags=re.MULTILINE)
    assert per_file, f"没能解析收集结果：\n{result.stdout[-500:]}"
    return sum(int(n) for n in per_file)


def _documented(path: Path) -> set[int]:
    """只挑和测试数有关的行：同一行里出现 pytest 或「项测试」。"""
    found: set[int] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if "pytest" not in line and "项测试" not in line:
            continue
        found.update(int(n) for n in _COUNT.findall(line))
    return found


def test_handoff_count_matches_reality():
    actual = _collected()
    wrong = {n for n in _documented(ROOT / "HANDOFF.md") if n != actual}
    assert not wrong, f"HANDOFF 写了 {sorted(wrong)}，实际是 {actual} 项"


def test_readme_count_matches_reality():
    actual = _collected()
    wrong = {n for n in _documented(ROOT / "README.md") if n != actual}
    assert not wrong, f"README 写了 {sorted(wrong)}，实际是 {actual} 项"


def test_reproduce_doc_count_matches_reality():
    """docs/reproduce.md 里写了「应看到 N passed」，也要对得上。"""
    actual = _collected()
    text = (ROOT / "docs" / "reproduce.md").read_text(encoding="utf-8")
    claim = re.search(r"应看到 (\d+) passed", text)
    assert claim, "reproduce.md 里没写「应看到 N passed」"
    assert int(claim.group(1)) == actual, f"reproduce.md 写 {claim.group(1)}，实际 {actual}"
