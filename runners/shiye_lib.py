"""把 shiye 当作库来跑。

为什么不用 HTTP：
* 只有 lib 模式能控制 ``now``——跨天场景必须能把时钟往后拨
* 只有 lib 模式能注入假 provider、关掉召回，做消融
* 每个用例一个独立临时库，互不污染

HTTP 模式留给最后的端到端冒烟，不在这一层。
"""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_SHIYE = Path(__file__).resolve().parents[2] / "shiye" / "src"


def _ensure_shiye_on_path() -> None:
    src = os.environ.get("SHIYE_SRC")
    path = Path(src) if src else DEFAULT_SHIYE
    if not path.exists():
        raise RuntimeError(f"找不到 shiye 源码：{path}（可用 SHIYE_SRC 指定）")
    while str(path) in sys.path:
        sys.path.remove(str(path))
    sys.path.insert(0, str(path))


_ensure_shiye_on_path()

from companion import db, persona as persona_mod, turn as turn_mod  # noqa: E402


@dataclass
class Reply:
    text: str
    ok: bool = True
    notes: dict = field(default_factory=dict)


def fake_provider(replies: list[str]):
    """复用 shiye 自带的 FakeProvider，避免两套实现漂移。"""
    from companion.provider import FakeProvider as _ShiyeFake

    return _ShiyeFake(replies)


class ShiyeRunner:
    """跑一个场景：若干轮用户输入，返回助手回复列表。"""

    def __init__(self, *, provider=None, persona_text: str | None = None) -> None:
        self.persona_text = persona_text or persona_mod.DEFAULT_PERSONA.render()
        self.provider = provider or _default_provider()
        self._tmpdir = tempfile.mkdtemp(prefix="shiye-bench-")

    # 每个场景一个全新库，避免记忆串味
    def _fresh_conn(self, index: int):
        path = Path(self._tmpdir) / f"case-{index}.db"
        conn = db.connect(path)
        db.apply_schema(conn)
        return conn

    def converse(
        self,
        turns: list[str],
        *,
        case_index: int = 0,
        start: datetime | None = None,
        day_gap: int = 0,
        boundary: tuple[str, ...] = (),
    ) -> list[Reply]:
        conn = self._fresh_conn(case_index)
        started = start or datetime(2026, 11, 1, 20, 0)
        replies: list[Reply] = []
        try:
            for step, text in enumerate(turns):
                moment = started + timedelta(days=day_gap * step)
                try:
                    result = turn_mod.run_turn(
                        conn, self.provider, text,
                        persona=self.persona_text,
                        boundaries=boundary,
                        now=moment,
                    )
                    replies.append(Reply(text=result.reply, notes=dict(result.notes)))
                except Exception as exc:  # noqa: BLE001 - 单个用例失败不该中断整批
                    replies.append(Reply(text="", ok=False, notes={"error": f"{type(exc).__name__}: {exc}"}))
        finally:
            conn.close()
        return replies


def _default_provider():
    """真实模型。没有 key 就报错，让调用方显式选 fake。"""
    from companion import provider as provider_mod

    provider_mod.load_env()
    if not os.environ.get("COMPANION_API_KEY"):
        raise RuntimeError("没有 API key；用 FakeProvider 或先配置 %LOCALAPPDATA%\\shiye\\.env")
    return provider_mod.OpenAICompatProvider()
