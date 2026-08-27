"""检索配置（DD-19 §12.3/§15）。

参数来自 `platform.config_revisions(namespace='retrieval')` 的 ACTIVE 版本；
未配置时使用代码默认值，`config_revision=0`。任务/检索开始时绑定一个完整配置快照，
运行中配置变化不影响当前检索（便于复现与 A/B）。

默认参数（DD-19 §12.3 调优起点）：每 query_text BM25 top 50、向量 top 50、
RRF k=60、融合去重后 top 40 送 Rerank、Rerank top 12 进证据选择、
最终证据 4～8（token 预算、来源覆盖、重复度约束）。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models.config import ConfigRevision

RETRIEVAL_NAMESPACE = "retrieval"
RETRIEVAL_SCHEMA_VERSION = "1"

DEFAULT_PARAMS: dict = {
    "bm25_top_k": 50,
    "vector_top_k": 50,
    "rrf_k": 60,
    "fusion_top_k": 40,
    "rerank_top_k": 12,
    "rerank_min_score": 0.2,
    "evidence_min": 4,
    "evidence_max": 8,
    "evidence_token_budget": 4000,
    "per_source_limit": 4,
}


@dataclass(frozen=True)
class RetrievalConfig:
    """一次检索绑定的配置快照。"""

    config_revision: int = 0
    schema_version: str = RETRIEVAL_SCHEMA_VERSION
    bm25_top_k: int = 50
    vector_top_k: int = 50
    rrf_k: int = 60
    fusion_top_k: int = 40
    rerank_top_k: int = 12
    rerank_min_score: float = 0.2
    evidence_min: int = 4
    evidence_max: int = 8
    evidence_token_budget: int = 4000
    per_source_limit: int = 4

    @property
    def params_snapshot(self) -> dict:
        return {
            "bm25_top_k": self.bm25_top_k,
            "vector_top_k": self.vector_top_k,
            "rrf_k": self.rrf_k,
            "fusion_top_k": self.fusion_top_k,
            "rerank_top_k": self.rerank_top_k,
            "rerank_min_score": self.rerank_min_score,
            "evidence_min": self.evidence_min,
            "evidence_max": self.evidence_max,
            "evidence_token_budget": self.evidence_token_budget,
            "per_source_limit": self.per_source_limit,
        }


def _active_config_revision(db: Session) -> ConfigRevision | None:
    return db.execute(
        select(ConfigRevision).where(
            ConfigRevision.namespace == RETRIEVAL_NAMESPACE,
            ConfigRevision.status == "ACTIVE",
        )
    ).scalars().first()


def _coerce_int(value, default: int) -> int:
    return int(value) if isinstance(value, (int, float)) and value > 0 else default


def _coerce_non_negative(value, default: float) -> float:
    return float(value) if isinstance(value, (int, float)) and value >= 0 else default


def load_retrieval_config(db: Session) -> RetrievalConfig:
    """读取当前 ACTIVE retrieval 配置并合并默认值。未配置返回默认值（revision=0）。"""
    rev = _active_config_revision(db)
    if rev is None:
        return RetrievalConfig()

    content = rev.content or {}
    params = dict(DEFAULT_PARAMS)
    for key in DEFAULT_PARAMS:
        if key in content and content[key] is not None:
            if isinstance(DEFAULT_PARAMS[key], int):
                params[key] = _coerce_int(content[key], DEFAULT_PARAMS[key])
            else:
                params[key] = _coerce_non_negative(content[key], DEFAULT_PARAMS[key])

    # 一致性约束：证据下限/上限、送 Rerank 数等
    evidence_min = min(params["evidence_min"], params["evidence_max"])
    return RetrievalConfig(
        config_revision=rev.id,
        schema_version=str(content.get("schema_version") or RETRIEVAL_SCHEMA_VERSION),
        bm25_top_k=params["bm25_top_k"],
        vector_top_k=params["vector_top_k"],
        rrf_k=params["rrf_k"],
        fusion_top_k=params["fusion_top_k"],
        rerank_top_k=params["rerank_top_k"],
        rerank_min_score=params["rerank_min_score"],
        evidence_min=evidence_min,
        evidence_max=params["evidence_max"],
        evidence_token_budget=params["evidence_token_budget"],
        per_source_limit=params["per_source_limit"],
    )
