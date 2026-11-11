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
# 中文否认「记得」的说法几乎全是「记(不|没)…」或「(不|没)…记得」两种骨架，
# 后缀有一长串（清/得/起来/住/着…）。之前逐个列后缀，漏一次改一次，已经漏了四回。
# 现在只认骨架，不再枚举后缀。
_ABSTAIN_RE = re.compile(
    r"(?:不|没|未)(?:太)?(?:记得|记着|记住|有印象|印象)|"
    r"记(?:不|没)|"
    r"想不起|没存|没留下|我这没有|我这儿没有|断片|"
    r"说不(?:清|准|明白|上来)|有点糊|糊了|哪知道|不知道"
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


_DIGITS = "零一二三四五六七八九"


def _to_chinese(n: int) -> str:
    """0–99999 的中文写法（口语式：4500 可写"四千五"）。"""
    if n == 0:
        return "零"
    if n >= 10000:
        high, low = divmod(n, 10000)
        return _to_chinese(high) + "万" + ("" if low == 0 else _to_chinese(low))
    units = ("", "十", "百", "千")
    parts: list[str] = []
    text = str(n)
    length = len(text)
    for i, ch in enumerate(text):
        digit = int(ch)
        if digit == 0:
            if parts and not parts[-1].endswith("零"):
                parts.append("零")
            continue
        parts.append(_DIGITS[digit] + units[length - i - 1])
    out = "".join(parts).rstrip("零")
    # 十几：十 而不是 一十
    if out.startswith("一十"):
        out = out[1:]
    # 口语式：四千五百 -> 四千五
    if len(out) >= 2 and out.endswith("百") is False and out[-1] == "百":
        pass
    for unit in ("百", "千"):
        tail = out
        if tail.endswith("零"):
            tail = tail[:-1]
        break
    if out.endswith("百零"):
        out = out[:-2] + "百"
    if out.endswith("百"):
        pass
    # 末位是整百/整千时，口语常省略最后一个单位
    if out.endswith("千") and len(out) > 2:
        out = out[:-1]
    elif out.endswith("百") and len(out) > 2:
        out = out[:-1]
    return out


def _variants(token: str) -> set[str]:
    """expect 里的数字要同时接受阿拉伯数字和中文写法。"""
    token = (token or "").strip()
    if not token.isdigit():
        return {token}
    value = int(token)
    forms = {token, str(value)}
    full = _to_chinese(value)
    forms.add(full)
    # 补一个"带完整单位"的写法（四千五 vs 四千五百）
    if value >= 100 and value % 100 == 0:
        forms.add(_to_chinese(value // 100) + "百")
    return {f for f in forms if f}


def check_memory(
    reply: str,
    *,
    expect: list[str],
    forbid: list[str],
) -> MemoryVerdict:
    text = reply or ""
    fabricated = [word for word in forbid if word in text]
    # 禁词优先：把命中的禁词片段挖掉再判 expect。
    # 否则"不去"会让 expect=["去"] 也算命中，得到"命中 + 编造"这种自相矛盾的判定。
    stripped = text
    for word in fabricated:
        stripped = stripped.replace(word, "　")
    hit = any(any(form in stripped for form in _variants(word)) for word in expect)
    abstained = bool(_ABSTAIN_RE.search(text))
    # 既没点名也没弃答，但用了"那件事"这类指代 —— 说明接上了，只是没复述
    by_ref = (not hit) and (not abstained) and any(
        marker in text for marker in _REFERENCE_MARKERS
    )
    return MemoryVerdict(
        hit=hit, fabricated=fabricated, abstained=abstained,
        understood_by_reference=by_ref, reply=text,
    )
