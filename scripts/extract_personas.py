"""从 shiye 的 git 历史里取出历代人格，供已知组校准使用。

为什么要这个：benchmark 的可信度取决于它能不能**复现已知的好坏排序**。
手上现成的"标准答案"就是主项目迭代过的那几版人格——用户当时的判断是
v1/v2 不够温柔、v3 太公式、v5 才满意。如果 benchmark 排不出来，判据就是坏的。

persona.py 是独立模块（只依赖 dataclasses），所以历史版本可以直接当模块加载。

用法::

    python scripts/extract_personas.py
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHIYE = ROOT.parent / "shiye"
OUT_DIR = ROOT / "data" / "personas"
MANIFEST = OUT_DIR / "manifest.json"

# 提交 → 我们给它起的版本名（按时间顺序）
VERSIONS: list[tuple[str, str, str]] = [
    ("861fb62", "p1-first", "第一版：温柔知心姐姐（只有形容词）"),
    ("e84093d", "p2-quantified", "第二版：量化参数 + 来历 + 12 条示范"),
    ("005f310", "p3-oneesan", "第三版：日系口吻（每句先来语气词）"),
    ("82770b8", "p4-openings", "第四版：拆掉开头公式，啊呀→哎呀"),
    ("2f876a2", "p5-nolife", "第五版：去掉具体生活细节（当前）"),
]


def _git_show(rev: str, path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{rev}:{path}"],
        cwd=str(SHIYE), capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(f"取不到 {rev}:{path}（{result.stderr.strip()[:120]}）")
    return result.stdout


def _load_module(path: Path):
    name = f"persona_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # dataclass 装饰器会去 sys.modules 里找所属模块，不登记就会炸
    sys.modules[name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def main() -> int:
    if not (SHIYE / ".git").exists():
        print(f"找不到 shiye 仓库：{SHIYE}", file=sys.stderr)
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []
    for rev, name, note in VERSIONS:
        target = OUT_DIR / f"{name}.py"
        target.write_text(_git_show(rev, "src/companion/persona.py"), encoding="utf-8")
        module = _load_module(target)
        persona = module.DEFAULT_PERSONA
        text = persona.render()
        manifest.append({
            "name": name,
            "rev": rev,
            "note": note,
            "chars": len(text),
            "examples": len(persona.examples),
        })
        print(f"{name:<14} {rev}  {len(text):>5} 字  {len(persona.examples)} 条示范")

    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n清单 -> {MANIFEST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
