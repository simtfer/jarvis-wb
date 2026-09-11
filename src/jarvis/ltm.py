"""长期记忆：本地 JSON 存储 + 关键词检索，零外部依赖。

设计取舍：
  - 存储就是一份 JSON 文件（默认 <项目>/data/memory.json），人能直接打开看、改、删；
  - 检索用词元重叠打分（拉丁词 + 中文字 + 相邻双字），不上向量库——
    等记忆量真的大了再换 sqlite/向量索引，接口不用变；
  - 读取命中会累计 hits，方便日后清理冷记忆。
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import settings


def _tokens(text: str) -> set[str]:
    """拉丁按词、中文按单字 + 相邻双字切词元。"""
    text = (text or "").lower()
    tokens = set(re.findall(r"[a-z0-9]+", text))
    cjk = re.findall(r"[\u4e00-\u9fff]", text)
    tokens.update(cjk)
    tokens.update(a + b for a, b in zip(cjk, cjk[1:]))
    return tokens


@dataclass
class MemoryItem:
    id: str
    text: str
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    hits: int = 0

    @classmethod
    def new(cls, text: str, tags: list[str] | None = None) -> "MemoryItem":
        return cls(
            id=uuid.uuid4().hex,
            text=text.strip(),
            tags=[t for t in (tags or []) if str(t).strip()],
            created_at=datetime.now().isoformat(timespec="seconds"),
        )


class LongTermMemory:
    """持久化的记忆条目集合。"""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or Path(settings.load().data_dir) / "memory.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._items: list[MemoryItem] = []
        self._load()

    # ---------- 持久化 ----------

    def _load(self) -> None:
        if not self.path.exists():
            self._items = []
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._items = [MemoryItem(**entry) for entry in raw]
        except (json.JSONDecodeError, TypeError, KeyError):
            # 文件损坏时备份后重开，不丢整个助手
            backup = self.path.with_suffix(".json.bak")
            if self.path.exists():
                self.path.replace(backup)
            self._items = []

    def _save(self) -> None:
        self.path.write_text(
            json.dumps([asdict(i) for i in self._items], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ---------- 增 ----------

    def remember(self, text: str, tags: list[str] | None = None) -> MemoryItem:
        """存一条记忆；内容重复时返回已有条目并更新时间戳语义（不重复入库）。"""
        text = (text or "").strip()
        if not text:
            raise ValueError("记忆内容不能为空")
        normalized = re.sub(r"\s+", "", text.lower())
        for item in self._items:
            if re.sub(r"\s+", "", item.text.lower()) == normalized:
                item.hits += 1
                self._save()
                return item
        item = MemoryItem.new(text, tags)
        self._items.append(item)
        self._save()
        return item

    # ---------- 查 ----------

    def recall(self, query: str, limit: int = 5) -> list[tuple[MemoryItem, float]]:
        """按词元重叠检索，返回 [(条目, 相关度)]，不相关的不凑数。"""
        query_tokens = _tokens(query)
        if not query_tokens:
            return []
        scored: list[tuple[float, MemoryItem]] = []
        for item in self._items:
            item_tokens = _tokens(item.text + " " + " ".join(item.tags))
            overlap = query_tokens & item_tokens
            if not overlap:
                continue
            score = len(overlap) / (len(query_tokens) ** 0.5)
            scored.append((score, item))
        scored.sort(key=lambda pair: (pair[0], pair[1].created_at), reverse=True)
        hits = scored[:limit]
        if hits:
            for _, item in hits:
                item.hits += 1
            self._save()
        return [(item, score) for score, item in hits]

    def all(self) -> list[MemoryItem]:
        return list(self._items)

    # ---------- 删 ----------

    def forget(self, ident: str) -> int:
        """按 id 前缀或内容关键词删除，返回删除条数。"""
        ident = (ident or "").strip().lower()
        if not ident:
            return 0
        before = len(self._items)
        self._items = [
            item
            for item in self._items
            if not (item.id.lower().startswith(ident) or ident in item.text.lower())
        ]
        removed = before - len(self._items)
        if removed:
            self._save()
        return removed

    def __len__(self) -> int:
        return len(self._items)


# ---------- 进程级单例 ----------

_LTM: LongTermMemory | None = None


def get_ltm() -> LongTermMemory:
    global _LTM
    if _LTM is None:
        _LTM = LongTermMemory()
    return _LTM


def reset_ltm() -> None:
    """测试用：丢弃单例，下次 get_ltm() 按当前配置重建。"""
    global _LTM
    _LTM = None
