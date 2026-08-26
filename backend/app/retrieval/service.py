"""检索服务（DD-19 §12）。独立 Retrieval Service：返回可解释证据，不生成答案。

流程（事务边界遵循 §8.5/DD-07 §16）：
1. QueryPlan（build_query_plan）+ 解析可查询版本（AC-RAG-001/002）；
2. 混合召回：每个 query_text BM25 top K + 向量 top K（向量依赖查询 Embedding）；
3. RRF 融合（k 可配）→ 相邻去重 → top fusion_top_k 送 Rerank；
4. Rerank top rerank_top_k 进证据选择；Rerank 失败/未配置降级 RRF 顺序；
5. 证据选择：token 预算 / 每来源上限 / 数量上限，最终证据 4～8；
6. 降级（DD-07 §15/§16）：查询 Embedding 失败 → BM25-only + EMBEDDING_FAILED；
   向量检索失败 → BM25-only + VECTOR_SEARCH_FAILED；BM25 失败 → 整体失败，
   不调用答案模型猜测；
7. 外部 HTTP（embed/rerank/search）不持有 DB 事务/行锁：读阶段结束后 commit 释放，
   结果收集后再短事务写 retrieval_runs / retrieval_candidates。

调用方注意：``retrieve`` 会在读阶段与写阶段各 commit 一次，不应在调用前于同一会话
保留未提交写入。
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from ..core.config import Settings, get_settings
from ..db.models.conversation import RetrievalCandidate, RetrievalRun
from ..llm.runtime import resolve_service_model
from ..llm.service import LLMConfigError
from ..model_gateway import create_gateway
from ..model_gateway.base import EmbeddingRequest, RerankRequest
from ..model_gateway.errors import GatewayError
from ..search import SearchAdapter, SearchAdapterError, get_search_adapter
from .config import RetrievalConfig, load_retrieval_config
from .core import (
    Candidate,
    dedupe_adjacent,
    evidence_status,
    rrf_fuse,
    select_evidence,
    sort_final,
)
from .errors import RetrievalError
from .filters import VersionRef, recheck_active_version_ids, resolve_active_versions
from .query_plan import build_query_plan
from .schemas import EvidenceItem, QueryPlan, RetrievalFilters

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmbedOutcome:
    embedding: list[float]
    model_key: str | None = None


@dataclass(frozen=True)
class RerankOutcome:
    results: list[tuple[int, float]]
    model_key: str | None = None


EmbedFn = Callable[[Session, str], EmbedOutcome]
RerankFn = Callable[[Session, str, list[str], int], RerankOutcome | None]


@dataclass
class RetrievalResult:
    query_plan: QueryPlan
    mode: str
    degradation_flags: list[str]
    ordered_candidates: list[Candidate]
    evidence: list[EvidenceItem]
    evidence_status: str
    candidate_counts: dict
    durations_ms: dict
    config_revision: int | None = None
    run_id: uuid.UUID | None = None


def _default_embed_query(db: Session, query: str) -> EmbedOutcome:
    """解析 DOCUMENT_EMBEDDING 模型并向量化查询问题。失败由调用方降级 BM25-only。"""
    resolved = resolve_service_model(db, "DOCUMENT_EMBEDDING")
    gateway = create_gateway(resolved)
    resp = gateway.embed(EmbeddingRequest(model=resolved.model_name, input=[query]))
    if not resp.data or not resp.data[0].embedding:
        raise RetrievalError("PROVIDER", "EMBED_EMPTY", "查询向量为空", retryable=False)
    return EmbedOutcome(embedding=list(resp.data[0].embedding), model_key=resolved.model_config_id)


def _default_rerank(
    db: Session, query: str, documents: list[str], top_n: int
) -> RerankOutcome | None:
    """解析可选 RETRIEVAL_RERANK 模型并重排。未配置返回 None（使用 RRF 顺序）。"""
    resolved = resolve_service_model(db, "RETRIEVAL_RERANK")
    if resolved is None:
        return None
    gateway = create_gateway(resolved)
    resp = gateway.rerank(
        RerankRequest(model=resolved.model_name, query=query, documents=documents, top_n=top_n)
    )
    return RerankOutcome(
        results=[(item.index, float(item.relevance_score)) for item in resp.results],
        model_key=resolved.model_config_id,
    )


class RetrievalService:
    def __init__(
        self,
        *,
        search: SearchAdapter,
        embed_fn: EmbedFn | None = None,
        rerank_fn: RerankFn | None = None,
        settings: Settings | None = None,
    ):
        self.search = search
        self._embed_fn = embed_fn or _default_embed_query
        self._rerank_fn = rerank_fn or _default_rerank
        self._settings = settings or get_settings()

    def retrieve(
        self,
        db: Session,
        question: str,
        filters: RetrievalFilters | None = None,
        *,
        operation: str = "ANSWER",
        persist: bool = True,
    ) -> RetrievalResult:
        started = time.monotonic()
        config = load_retrieval_config(db)
        plan = build_query_plan(db, question, filters, operation=operation)
        refs = resolve_active_versions(db, filters or RetrievalFilters())
        refs_by_version = {str(ref.version_id): ref for ref in refs}
        allowed_version_ids = list(refs_by_version.keys())
        # 读阶段结束，释放读事务：外部 HTTP 调用不再持有 DB 事务/行锁
        db.commit()

        mode = "HYBRID"
        flags: list[str] = []
        embed_model_key: str | None = None
        rerank_model_key: str | None = None
        stage: dict[str, float] = {}

        query_embedding: list[float] | None = None
        if allowed_version_ids:
            # 1) 查询 Embedding（可选；失败降级 BM25-only）
            if config.vector_top_k > 0:
                t0 = time.monotonic()
                try:
                    outcome = self._embed_fn(db, plan.normalized_question)
                    query_embedding = list(outcome.embedding)
                    embed_model_key = outcome.model_key
                except (LLMConfigError, GatewayError, RetrievalError):
                    flags.append("EMBEDDING_FAILED")
                    mode = "BM25_ONLY"
                stage["embed_ms"] = (time.monotonic() - t0) * 1000

            # 2) 混合召回
            bm25_ranks: dict[str, int] = {}
            vector_ranks: dict[str, int] = {}
            bm25_scores: dict[str, float] = {}
            vector_scores: dict[str, float] = {}
            doc_by_id: dict[str, dict] = {}
            bm25_failed: SearchAdapterError | None = None

            t0 = time.monotonic()
            for qt in plan.query_texts:
                if bm25_failed is None:
                    try:
                        res = self.search.search(
                            query_text=qt, retrieval_type="bm25",
                            top_k=config.bm25_top_k, version_ids=allowed_version_ids,
                        )
                        for i, hit in enumerate(res.hits, start=1):
                            cid = hit.get("chunk_id")
                            if not cid:
                                continue
                            bm25_ranks.setdefault(cid, i)
                            bm25_scores.setdefault(cid, float(hit.get("_score") or 0.0))
                            doc_by_id.setdefault(cid, hit)
                    except SearchAdapterError as exc:
                        bm25_failed = exc
                if query_embedding is not None:
                    try:
                        res = self.search.search(
                            query_text=qt, retrieval_type="vector", embedding=query_embedding,
                            top_k=config.vector_top_k, version_ids=allowed_version_ids,
                        )
                        for i, hit in enumerate(res.hits, start=1):
                            cid = hit.get("chunk_id")
                            if not cid:
                                continue
                            vector_ranks.setdefault(cid, i)
                            vector_scores.setdefault(cid, float(hit.get("_score") or 0.0))
                            doc_by_id.setdefault(cid, hit)
                    except SearchAdapterError:
                        flags.append("VECTOR_SEARCH_FAILED")
                        mode = "BM25_ONLY"
                        query_embedding = None
            stage["search_ms"] = (time.monotonic() - t0) * 1000

            # BM25 失败 → 整体检索失败（不静默 vector-only，不调用答案模型猜测）
            if bm25_failed is not None:
                if persist:
                    self._persist_failed(
                        db, plan, config, "FAILED", flags + ["BM25_FAILED"],
                        "SEARCH_BM25_FAILED",
                    )
                raise RetrievalError(
                    "PROVIDER", "SEARCH_BM25_FAILED", "BM25 检索不可用",
                    retryable=bm25_failed.retryable,
                ) from bm25_failed

            # 3) RRF 融合 → 相邻去重 → top fusion_top_k
            rrf_scores = rrf_fuse(bm25_ranks, vector_ranks, config.rrf_k)
            candidates: list[Candidate] = []
            for cid, score in rrf_scores.items():
                doc = doc_by_id[cid]
                candidates.append(
                    Candidate(
                        chunk_id=cid,
                        source_id=str(doc.get("source_id") or ""),
                        version_id=str(doc.get("version_id") or ""),
                        doc=doc,
                        bm25_rank=bm25_ranks.get(cid),
                        vector_rank=vector_ranks.get(cid),
                        bm25_score=bm25_scores.get(cid),
                        vector_score=vector_scores.get(cid),
                        rrf_score=score,
                    )
                )
            candidates = dedupe_adjacent(candidates)
            candidates = sort_final(candidates)[: config.fusion_top_k]

            # 4) Rerank（可选；失败/为空降级 RRF 顺序 + RERANK_FAILED）
            if candidates:
                try:
                    outcome = self._rerank_fn(
                        db,
                        plan.normalized_question,
                        [c.doc.get("content") or "" for c in candidates],
                        config.rerank_top_k,
                    )
                    rerank_model_key = outcome.model_key if outcome is not None else None
                    if outcome is not None and outcome.results:
                        by_index = {i: c for i, c in enumerate(candidates)}
                        reranked: list[Candidate] = []
                        for idx, score in outcome.results:
                            cand = by_index.get(idx)
                            if cand is None:
                                continue
                            cand.rerank_score = float(score)
                            reranked.append(cand)
                        if config.rerank_min_score > 0:
                            reranked = [
                                c for c in reranked if (c.rerank_score or 0.0) >= config.rerank_min_score
                            ]
                        candidates = reranked
                    elif outcome is not None:
                        flags.append("RERANK_FAILED")
                except (LLMConfigError, GatewayError, RetrievalError):
                    flags.append("RERANK_FAILED")

            # 5) 证据选择前 DB 复核（DD-07 §6.2：索引可能滞后，不能仅依赖索引）
            active_now = recheck_active_version_ids(db)
            for cand in candidates:
                if cand.version_id not in active_now:
                    cand.exclusion_reason = "VERSION_NOT_ACTIVE"
            evidence_cands = select_evidence(
                [c for c in candidates if c.version_id in active_now],
                evidence_min=config.evidence_min,
                evidence_max=config.evidence_max,
                evidence_token_budget=config.evidence_token_budget,
                per_source_limit=config.per_source_limit,
            )

            evidence = [
                self._to_evidence(cand, refs_by_version, f"E{i}")
                for i, cand in enumerate(evidence_cands, start=1)
            ]
            status = evidence_status(len(evidence_cands), config.evidence_min)
            counts = {
                "bm25_hits": len(bm25_ranks),
                "vector_hits": len(vector_ranks),
                "fused": len(rrf_scores),
                "reranked": len(candidates),
                "evidence": len(evidence_cands),
            }
        else:
            # 没有可查询版本：不调用外部模型/检索，直接返回空证据
            candidates = []
            evidence = []
            status = "INSUFFICIENT"
            counts = {"bm25_hits": 0, "vector_hits": 0, "fused": 0, "reranked": 0, "evidence": 0}

        durations_ms = dict(stage)
        durations_ms["total_ms"] = (time.monotonic() - started) * 1000

        run_id: uuid.UUID | None = None
        if persist:
            run = RetrievalRun(
                operation=plan.operation,
                normalized_question=plan.normalized_question,
                query_texts=plan.query_texts,
                product_id=plan.product_id,
                version_ids=_uuid_list(plan.version_ids),
                document_type_ids=_uuid_list(plan.document_type_ids),
                mode=mode,
                degradation_flags=flags,
                status="SUCCEEDED",
                config_revision=config.config_revision,
                embedding_model_key=embed_model_key,
                rerank_model_key=rerank_model_key,
                params_snapshot=config.params_snapshot,
                stage_duration_ms=durations_ms,
                candidate_counts=counts,
                evidence_status=status,
                evidence_count=len(evidence_cands) if allowed_version_ids else 0,
            )
            db.add(run)
            db.flush()
            for rank, cand in enumerate(candidates, start=1):
                cand.final_rank = rank
                db.add(
                    RetrievalCandidate(
                        retrieval_run_id=run.id,
                        chunk_id=uuid.UUID(cand.chunk_id),
                        source_id=_uuid_or_none(cand.source_id),
                        version_id=_uuid_or_none(cand.version_id),
                        ordinal=cand.doc.get("ordinal"),
                        rank=rank,
                        bm25_rank=cand.bm25_rank,
                        vector_rank=cand.vector_rank,
                        bm25_score=cand.bm25_score,
                        vector_score=cand.vector_score,
                        rrf_score=cand.rrf_score,
                        rerank_score=cand.rerank_score,
                        final_score=cand.final_score,
                        is_evidence=cand.is_evidence,
                        evidence_rank=cand.evidence_rank,
                        exclusion_reason=cand.exclusion_reason,
                        score_details=cand.score_details,
                        title_snapshot=(cand.doc.get("title") or "")[:512] or None,
                        content_sha256=cand.doc.get("content_sha256"),
                    )
                )
            db.commit()
            run_id = run.id

        logger.info(
            "retrieval_done",
            extra={
                "mode": mode,
                "flags": flags,
                "evidence_count": len(evidence),
                "evidence_status": status,
                "run_id": str(run_id) if run_id else None,
                "bm25_hits": counts.get("bm25_hits"),
                "vector_hits": counts.get("vector_hits"),
                "total_ms": round(durations_ms.get("total_ms", 0), 3),
            },
        )

        return RetrievalResult(
            query_plan=plan,
            mode=mode,
            degradation_flags=flags,
            ordered_candidates=candidates,
            evidence=evidence,
            evidence_status=status,
            candidate_counts=counts,
            durations_ms=durations_ms,
            config_revision=config.config_revision,
            run_id=run_id,
        )

    def _to_evidence(
        self, cand: Candidate, refs_by_version: dict[str, VersionRef], evidence_id: str
    ) -> EvidenceItem:
        ref = refs_by_version.get(cand.version_id)
        return EvidenceItem(
            evidence_id=evidence_id,
            chunk_id=uuid.UUID(cand.chunk_id),
            source_id=uuid.UUID(cand.source_id),
            document_version_id=uuid.UUID(cand.version_id),
            content=cand.doc.get("content") or "",
            title=ref.display_name if ref else (cand.doc.get("title") or ""),
            heading_path=cand.doc.get("heading_path") or [],
            locator=cand.doc.get("locator") or {},
            source_priority=ref.source_priority if ref else 0,
            source_updated_at=ref.source_modified_at if ref else None,
            score_details=cand.score_details,
        )

    def _persist_failed(
        self,
        db: Session,
        plan: QueryPlan,
        config: RetrievalConfig,
        mode: str,
        flags: list[str],
        error_code: str,
    ) -> None:
        db.add(
            RetrievalRun(
                operation=plan.operation,
                normalized_question=plan.normalized_question,
                query_texts=plan.query_texts,
                product_id=plan.product_id,
                version_ids=_uuid_list(plan.version_ids),
                document_type_ids=_uuid_list(plan.document_type_ids),
                mode=mode,
                degradation_flags=flags,
                status="FAILED",
                error_code=error_code,
                config_revision=config.config_revision,
                params_snapshot=config.params_snapshot,
            )
        )
        db.commit()


def _uuid_list(values: list[uuid.UUID]) -> list[str] | None:
    return [str(v) for v in values] if values else None


def _uuid_or_none(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        return None


def build_retrieval_service(
    search: SearchAdapter | None = None,
    *,
    embed_fn: EmbedFn | None = None,
    rerank_fn: RerankFn | None = None,
    settings: Settings | None = None,
) -> RetrievalService:
    """默认工厂：search 未注入时按 settings 创建适配器（fake/opensearch）。"""
    settings = settings or get_settings()
    return RetrievalService(
        search=search or get_search_adapter(settings),
        embed_fn=embed_fn,
        rerank_fn=rerank_fn,
        settings=settings,
    )
