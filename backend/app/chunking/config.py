"""切片配置（DD-19 §10、§15）。

- 目标/硬上限/最小 token、相邻重叠、表格按行拆分上限来自
  `platform.config_revisions(namespace='chunking')` 的 ACTIVE 版本；
  未配置时使用代码默认值，`config_revision=0`。
- 配置在任务启动时读取并绑定为快照；运行中发布新配置不影响当前任务。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models.config import ConfigRevision

CHUNKING_NAMESPACE = "chunking"
CHUNKING_SCHEMA_VERSION = "1"

# 初始参数（DD-19 §10.1）：目标 450~700、硬上限 900、最小 100、重叠 60~100；
# 表格优先完整保留，超限按行拆分并重复表头。
DEFAULT_CHUNKING = {
    "target_min_tokens": 450,
    "target_max_tokens": 700,
    "hard_max_tokens": 900,
    "min_tokens": 100,
    "overlap_tokens": 80,
    "max_table_split_rows": 50,
}


@dataclass(frozen=True)
class ChunkingConfig:
    """一次切片任务绑定的配置快照。"""

    config_revision: int = 0
    schema_version: str = CHUNKING_SCHEMA_VERSION
    target_min_tokens: int = DEFAULT_CHUNKING["target_min_tokens"]
    target_max_tokens: int = DEFAULT_CHUNKING["target_max_tokens"]
    hard_max_tokens: int = DEFAULT_CHUNKING["hard_max_tokens"]
    min_tokens: int = DEFAULT_CHUNKING["min_tokens"]
    overlap_tokens: int = DEFAULT_CHUNKING["overlap_tokens"]
    max_table_split_rows: int = DEFAULT_CHUNKING["max_table_split_rows"]

    def __post_init__(self) -> None:
        # 防御：非法配置按默认回退，避免越界导致无限循环/空切片（逐字段，不跨字段比较）
        if not (self.target_max_tokens > 0):
            object.__setattr__(self, "target_max_tokens", DEFAULT_CHUNKING["target_max_tokens"])
        if not (self.hard_max_tokens >= self.target_max_tokens):
            object.__setattr__(self, "hard_max_tokens", self.target_max_tokens)
        if self.min_tokens < 0:
            object.__setattr__(self, "min_tokens", 0)
        if self.overlap_tokens < 0:
            object.__setattr__(self, "overlap_tokens", 0)


def _active_config_revision(db: Session) -> ConfigRevision | None:
    return db.execute(
        select(ConfigRevision).where(
            ConfigRevision.namespace == CHUNKING_NAMESPACE,
            ConfigRevision.status == "ACTIVE",
        )
    ).scalars().first()


def load_chunking_config(db: Session) -> ChunkingConfig:
    """读取当前 ACTIVE chunking 配置。未配置时返回代码默认值（config_revision=0）。

    已配置时缺失字段回退默认值，保证向前兼容。只读，不触发写入。
    """
    rev = _active_config_revision(db)
    if rev is None:
        return ChunkingConfig()
    content = rev.content or {}

    def _int(key: str, default: int) -> int:
        value = content.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
        return default

    return ChunkingConfig(
        config_revision=rev.id,
        schema_version=str(content.get("schema_version") or CHUNKING_SCHEMA_VERSION),
        target_min_tokens=_int("target_min_tokens", DEFAULT_CHUNKING["target_min_tokens"]),
        target_max_tokens=_int("target_max_tokens", DEFAULT_CHUNKING["target_max_tokens"]),
        hard_max_tokens=_int("hard_max_tokens", DEFAULT_CHUNKING["hard_max_tokens"]),
        min_tokens=_int("min_tokens", DEFAULT_CHUNKING["min_tokens"]),
        overlap_tokens=_int("overlap_tokens", DEFAULT_CHUNKING["overlap_tokens"]),
        max_table_split_rows=_int("max_table_split_rows", DEFAULT_CHUNKING["max_table_split_rows"]),
    )
