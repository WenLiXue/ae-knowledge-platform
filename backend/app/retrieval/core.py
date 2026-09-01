"""检索核心纯函数（DD-19 §12.3）：RRF 融合、相邻去重、证据选择。

无外部依赖（DB/模型/检索引擎），便于单元测试。参数来自 RetrievalConfig，
不在此硬编码为最终值。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..chunking.tokens import estimate_tokens


@dataclass
class Candidate:
    """一个融合候选。doc 为索引文档字段；各阶段 rank/分数用于记录与排序。"""

    chunk_id: str
    source_id: str
    version_id: str
    doc: dict = field(default_factory=dict)
    bm25_rank: int | None = None
    vector_rank: int | None = None
    bm25_score: float | None = None
    vector_score: float | None = None
    rrf_score: float = 0.0
    rerank_score: float | None = None
    final_rank: int = 0
    is_evidence: bool = False
    evidence_rank: int | None = None
    exclusion_reason: str | None = None

    @property
    def final_score(self) -> float:
        """最终排序分数：优先 Rerank 分数，否则 RRF 分数。"""
        return self.rerank_score if self.rerank_score is not None else self.rrf_score

    @property
    def score_details(self) -> dict:
        return {
            "bm25_rank": self.bm25_rank,
            "vector_rank": self.vector_rank,
            "bm25_score": self.bm25_score,
            "vector_score": self.vector_score,
            "rrf_score": self.rrf_score,
            "rerank_score": self.rerank_score,
            "final_score": self.final_score,
        }


def rrf_fuse(bm25_ranks: dict[str, int], vector_ranks: dict[str, int], k: int) -> dict[str, float]:
    """RRF(d) = Σ 1/(k + rank_i(d))，rank 从 1 开始；相同 chunk 只出现一次。"""
    scores: dict[str, float] = {}
    for chunk_id, rank in bm25_ranks.items():
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    for chunk_id, rank in vector_ranks.items():
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return scores


def _same_section(a: Candidate, b: Candidate) -> bool:
    if (a.doc.get("heading_path") or []) != (b.doc.get("heading_path") or []):
        return False
    a_ord = a.doc.get("ordinal")
    b_ord = b.doc.get("ordinal")
    return isinstance(a_ord, int) and isinstance(b_ord, int) and abs(a_ord - b_ord) <= 1


def dedupe_adjacent(candidates: list[Candidate]) -> list[Candidate]:
    """按 RRF 降序去重：同来源相邻（ordinal 差 1）且同一 heading_path 的候选只保留
    分数较高者，避免一个长章节占满候选（DD-07 §8.2）。"""
    ordered = sorted(candidates, key=lambda c: -c.rrf_score)
    kept: list[Candidate] = []
    for cand in ordered:
        prev = kept[-1] if kept else None
        if prev is not None and _same_section(prev, cand):
            continue
        kept.append(cand)
    return kept


def sort_final(candidates: list[Candidate]) -> list[Candidate]:
    """按最终顺序排序：有 Rerank 分数按 Rerank 降序（同分按 RRF），否则按 RRF 降序。"""
    has_rerank = any(c.rerank_score is not None for c in candidates)
    if has_rerank:
        return sorted(candidates, key=lambda c: (-(c.rerank_score or 0.0), -c.rrf_score))
    return sorted(candidates, key=lambda c: -c.rrf_score)


def _tokens(cand: Candidate) -> int:
    tc = cand.doc.get("token_count")
    if isinstance(tc, int) and tc > 0:
        return tc
    return estimate_tokens(cand.doc.get("content") or "")


def select_evidence(
    candidates: list[Candidate],
    *,
    evidence_min: int,
    evidence_max: int,
    evidence_token_budget: int,
    per_source_limit: int,
    score_floor: float = 0.0,
    score_margin: float = 0.0,
) -> list[Candidate]:
    """从已排序候选中选择最终证据（DD-19 §12.4/DD-07 §8.3）。

    约束依次为：证据数量上限、token 预算、每来源上限。直接在候选上标注
    is_evidence/evidence_rank/exclusion_reason。少于 evidence_min 时返回实际数量，
    由调用方结合 evidence_min 判定证据状态。
    """
    kept: list[Candidate] = []
    source_count: dict[str, int] = {}
    total_tokens = 0
    rerank_scores = [c.rerank_score for c in candidates if c.rerank_score is not None]
    top_rerank_score = max(rerank_scores) if rerank_scores else None
    relative_floor = (
        top_rerank_score - score_margin
        if score_margin > 0 and top_rerank_score is not None
        else 0.0
    )
    effective_floor = max(score_floor, relative_floor)
    for cand in candidates:
        if len(kept) >= evidence_max:
            cand.exclusion_reason = "EVIDENCE_MAX"
            continue
        if cand.rerank_score is not None and cand.rerank_score < effective_floor:
            cand.exclusion_reason = "SCORE_BELOW_THRESHOLD"
            continue
        tokens = _tokens(cand)
        if total_tokens + tokens > evidence_token_budget:
            cand.exclusion_reason = "TOKEN_BUDGET"
            continue
        if source_count.get(cand.source_id, 0) >= per_source_limit:
            cand.exclusion_reason = "PER_SOURCE_LIMIT"
            continue
        cand.is_evidence = True
        cand.evidence_rank = len(kept) + 1
        cand.final_rank = len(kept) + 1
        kept.append(cand)
        source_count[cand.source_id] = source_count.get(cand.source_id, 0) + 1
        total_tokens += tokens
    return kept


def evidence_status(evidence_count: int, evidence_min: int) -> str:
    """确定性证据充分度信号（DD-07 §10）：SUFFICIENT/PARTIAL/INSUFFICIENT。"""
    if evidence_count >= evidence_min:
        return "SUFFICIENT"
    if evidence_count > 0:
        return "PARTIAL"
    return "INSUFFICIENT"
