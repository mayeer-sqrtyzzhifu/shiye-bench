"""记忆接地判定：命中 / 编造 / 诚实说不知道。

三个指标，全部规则化：

* ``hit``       —— 期望的事实片段是否出现
* ``fabricated``—— 是否出现用例明确禁止的编造内容
* ``abstain``   —— 没命中时，是否诚实地说"不记得"，而不是含糊糊弄

第三条容易被忽略：**不记得却说"嗯，我记得"**比直接承认不知道更糟。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 指代理解：没说具体内容，但明显知道"说的是哪件事"
_REFERENCE_MARKERS = (
    "那事", "那件", "那茬", "这事", "那回", "那次说",
    "又来", "刚说完", "又说", "那顿饭", "上次说",
)

# "我不记得"的说法很多，且词序会变（"不记得"/"记不得"），所以用正则而不是词表
# 中文否定说法太多，与其穷举，不如按结构匹配：
#   「不/没/未 + 记得/记着/记住/印象」和「记 + 不/没 + 起来/住/得/着」
_ABSTAIN_RE = re.compile(
    r"(?:不|没|未)(?:太)?(?:记得|记着|记住|记得住|有印象|印象)|"
    r"记(?:不|没)(?:起来|住|得|着)|"
    r"没存|没留下|我这没有|我这儿没有|想不起来|断片|说不准|有点糊|糊了"
)


@dataclass
class MemoryVerdict:
    hit: bool
    fabricated: list[str] = field(default_factory=list)
    abstained: bool = False
    understood_by_reference: bool = False
    reply: str = ""

    @property
    def ok(self) -> bool:
        return self.hit and not self.fabricated

    def summary(self) -> str:
        if self.hit:
            parts = ["命中"]
        elif self.understood_by_reference:
            parts = ["指代理解"]
        else:
            parts = ["未命中"]
        if self.fabricated:
            parts.append(f"编造:{','.join(self.fabricated)}")
        if self.abstained:
            parts.append("诚实弃答")
        return "｜".join(parts)


def check_memory(
    reply: str,
    *,
    expect: list[str],
    forbid: list[str],
) -> MemoryVerdict:
    text = reply or ""
    hit = any(word in text for word in expect)
    fabricated = [word for word in forbid if word in text]
    abstained = bool(_ABSTAIN_RE.search(text))
    # 既没点名也没弃答，但用了"那件事"这类指代 —— 说明接上了，只是没复述
    by_ref = (not hit) and (not abstained) and any(
        marker in text for marker in _REFERENCE_MARKERS
    )
    return MemoryVerdict(
        hit=hit, fabricated=fabricated, abstained=abstained,
        understood_by_reference=by_ref, reply=text,
    )
