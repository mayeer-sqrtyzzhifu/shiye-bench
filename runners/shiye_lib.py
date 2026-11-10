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

from companion import db, extract as extract_mod  # noqa: E402
from companion import persona as persona_mod, turn as turn_mod  # noqa: E402


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

    def __init__(self, *, provider=None, persona_text: str | None = None,
                 with_extraction: bool = True) -> None:
        self.persona_text = persona_text or persona_mod.DEFAULT_PERSONA.render()
        self.provider = provider or _default_provider()
        # web 服务里有抽取 worker，lib 模式没有；不显式跑就只测到原文 FTS 这一条路
        self.with_extraction = with_extraction
        self._tmpdir = tempfile.mkdtemp(prefix="shiye-bench-")


    def _extract_now(self, conn, result, user_text: str) -> None:
        """把 web 服务里的异步抽取在这里同步跑掉。

        这是 lib 模式最容易被忽略的差别：不跑抽取，跨天记忆就只剩原文 FTS，
        测出来的"记不住"其实是测试方法的问题，不是产品的问题。
        """
        if result.user_message_id is None:
            return
        turn_id = f"{result.session_id}:{result.turn_index}"
        extract_mod.enqueue_extract(conn, turn_id, {
            "user_text": user_text,
            "assistant_text": result.reply,
            "evidence_ids": [result.user_message_id],
        })
        try:
            extract_mod.run_pending(conn, self.provider)
        except Exception as exc:  # noqa: BLE001 - 抽取失败不该中断对话
            result.notes["extract_error"] = f"{type(exc).__name__}: {exc}"

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
        day_offsets: list[int] | None = None,
        boundary: tuple[str, ...] = (),
    ) -> list[Reply]:
        conn = self._fresh_conn(case_index)
        started = start or datetime(2026, 11, 1, 20, 0)
        replies: list[Reply] = []
        try:
            for step, text in enumerate(turns):
                # day_offsets 优先：跨天场景需要"第 0 天埋、第 1 天问"这种精确控制
                offset = day_offsets[step] if day_offsets else day_gap * step
                moment = started + timedelta(days=offset)
                try:
                    result = turn_mod.run_turn(
                        conn, self.provider, text,
                        persona=self.persona_text,
                        boundaries=boundary,
                        now=moment,
                    )
                    replies.append(Reply(text=result.reply, notes=dict(result.notes)))
                    if self.with_extraction and result.persisted:
                        self._extract_now(conn, result, text)
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
