"""从 GitHub 采样 SmileChat（qiuhuachuan/smile）的对话文件。

为什么要采样而不是全量 clone：仓库约 276 MB、一万多个 JSON，做格式分析与
统计只需要上百个样本；全量下载留给真正要用的时候。

采样是**确定性**的（固定 seed），所以别人跑同样的命令会得到同一批文件。

用法::

    python scripts/fetch_smilechat.py --count 120
    python scripts/fetch_smilechat.py --count 120 --force   # 重新下载
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "smilechat"
MANIFEST = ROOT / "data" / "smilechat-manifest.json"

REPO = "qiuhuachuan/smile"
BRANCH = "main"
TREE_API = f"https://api.github.com/repos/{REPO}/git/trees/{BRANCH}?recursive=1"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/"
SEED = 20261110


def _get(url: str, *, timeout: int = 30, retries: int = 3) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "shiye-bench"})
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError) as exc:  # noqa: PERF203
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"下载失败：{url}（{last}）")


def list_dialogue_files() -> list[str]:
    payload = json.loads(_get(TREE_API, timeout=60))
    paths = [
        item["path"]
        for item in payload.get("tree", [])
        if item["type"] == "blob"
        and item["path"].startswith("data/")
        and item["path"].endswith(".json")
    ]
    return sorted(paths)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=120)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("[1/3] 列出仓库文件…")
    files = list_dialogue_files()
    print(f"      共 {len(files)} 个对话文件")

    rng = random.Random(SEED)
    count = min(args.count, len(files))
    picked = rng.sample(files, count)
    print(f"[2/3] 采样 {count} 个（seed={SEED}）")

    manifest: list[dict] = []
    failures: list[str] = []
    for index, path in enumerate(picked, 1):
        target = DATA_DIR / Path(path).name
        if target.exists() and not args.force:
            manifest.append({"path": path, "bytes": target.stat().st_size, "cached": True})
            continue
        try:
            blob = _get(RAW_BASE + path)
        except RuntimeError as exc:
            failures.append(f"{path}: {exc}")
            continue
        target.write_bytes(blob)
        manifest.append({"path": path, "bytes": len(blob), "cached": False})
        if index % 20 == 0:
            print(f"      {index}/{count}…")

    print(f"[3/3] 完成：成功 {len(manifest)}，失败 {len(failures)}")
    MANIFEST.write_text(
        json.dumps(
            {"repo": REPO, "branch": BRANCH, "seed": SEED, "files": manifest,
             "failures": failures},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"      manifest -> {MANIFEST.relative_to(ROOT)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
