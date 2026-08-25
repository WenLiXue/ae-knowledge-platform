"""检索服务集成测试（DD-19 §12，Phase 5）。

覆盖：
- 混合召回返回可解释证据（chunk/版本/标题/章节/locator/score_details），不生成答案；
- retrieval_runs / retrieval_candidates 持久化（(run_id, chunk_id) 唯一）；
- AC-RAG-001：只召回 QUERYABLE current_version/current generation，索引残留旧版本不召回；
- AC-RAG-002：产品/版本/文档类型条件真实进入过滤；
- 降级：查询 Embedding 失败 → BM25-only + EMBEDDING_FAILED；向量检索失败 →
  BM25-only + VECTOR_SEARCH_FAILED；Rerank 失败 → RRF 顺序 + RERANK_FAILED；
  BM25 失败 → 整体失败并记录 FAILED run，不生成答案；
- 无可查询文档 → INSUFFICIENT 空证据。

模型调用注入假 embed/rerank 函数；检索引擎注入 FakeSearchAdapter。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.model_gateway.errors import GatewayError
from app.retrieval.errors import RetrievalError
from app.retrieval.schemas import RetrievalFilters
from app.retrieval.service import RerankOutcome, RetrievalService
from app.search.base import SearchAdapterError
from app.search.fake import FakeSearchAdapter

from _seed_retrieval import add_document, make_embedding, seed_catalog


def _fake_embed(db, query: str):
    return _embed_outcome(query)


def _embed_outcome(query: str):
    from app.retrieval.service import EmbedOutcome

    return EmbedOutcome(embedding=make_embedding(query), model_key="fake-embed")


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = (sum(x * x for x in a)) ** 0.5
    nb = (sum(x * x for x in b)) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _fake_rerank(db, query: str, documents: list[str], top_n: int):
    # 确定性：按查询与正文的词袋向量余弦降序（与共享 token 越多越靠前）
    qv = make_embedding(query)
    scored = [(i, _cosine(qv, make_embedding(doc))) for i, doc in enumerate(documents)]
    scored.sort(key=lambda item: item[1], reverse=True)
    return RerankOutcome(results=scored[:top_n], model_key="fake-rerank")


def _reverse_rerank(db, query: str, documents: list[str], top_n: int):
    # 确定性：按 (index+1) 降序 → 把融合输入的最后候选排到最前，用于验证排序被采用
    results = [(i, float(i + 1)) for i in range(len(documents))]
    results.sort(key=lambda item: item[1], reverse=True)
    return RerankOutcome(results=results[:top_n], model_key="fake-rerank")


def _seed_full(db, adapter, *, spec_chunks=None, wp_chunks=None):
    cat = seed_catalog(db)
    spec_chunks = spec_chunks or [
        "E3800 防病毒吞吐量 3.5G 物理吞吐量 15G 内存 64G DDR4",
        "T90000 CPU AMD EPYC 7H12 内存 256GB 磁盘 16TB 接口双口万兆",
        "G1280D 国产化型号 海光 C86 3350 8核16线程 32GB 4TB",
    ]
    wp_chunks = wp_chunks or [
        "信舷防毒墙是下一代内容安全网关 集成自研引擎 威胁情报 高性能流扫描",
        "支持网桥模式 路由模式 反向代理模式 部署灵活",
        "多引擎协同检测 变种检出率提升至 98% 脱壳技术 20+",
    ]
    spec_doc = add_document(
        db, adapter, display_name="AE 硬件规格", doc_type=cat["spec"],
        product=cat["product"], product_version=cat["product_version"], chunks=spec_chunks,
    )
    wp_doc = add_document(
        db, adapter, display_name="V7.0 产品白皮书", doc_type=cat["wp"],
        product=cat["product"], product_version=cat["product_version"], chunks=wp_chunks,
    )
    db.commit()
    return cat, spec_doc, wp_doc


def _service(adapter, *, embed=None, rerank=None) -> RetrievalService:
    return RetrievalService(
        search=adapter,
        embed_fn=embed or _fake_embed,
        rerank_fn=rerank or _fake_rerank,
    )


def test_hybrid_retrieval_returns_explainable_evidence() -> None:
    with SessionLocal() as db:
        adapter = FakeSearchAdapter()
        cat, spec_doc, wp_doc = _seed_full(db, adapter)
        svc = _service(adapter)

        result = svc.retrieve(db, "E3800 的防病毒吞吐量和内存是多少？")

        assert result.mode == "HYBRID"
        assert result.degradation_flags == []
        assert result.evidence_status == "SUFFICIENT"
        assert 4 <= len(result.evidence) <= 8
        # 可解释证据字段完整，不生成答案
        ev = result.evidence[0]
        assert ev.evidence_id.startswith("E")
        assert ev.chunk_id
        assert ev.source_id in {spec_doc.source.id, wp_doc.source.id}
        assert ev.document_version_id
        assert ev.title in {"AE 硬件规格", "V7.0 产品白皮书"}
        assert isinstance(ev.heading_path, list)
        assert ev.locator.get("element_ids")
        assert set(ev.score_details) >= {"bm25_rank", "vector_rank", "rrf_score", "rerank_score", "final_score"}
        # 命中的第一条证据应包含查询相关 token
        assert "E3800" in ev.content or "吞吐" in ev.content or "内存" in ev.content


def test_retrieval_run_and_candidates_persisted() -> None:
    from app.db.models.conversation import RetrievalCandidate, RetrievalRun

    with SessionLocal() as db:
        adapter = FakeSearchAdapter()
        _seed_full(db, adapter)
        svc = _service(adapter)

        result = svc.retrieve(db, "T90000 的 CPU 和内存是什么？")
        run_id = result.run_id
        assert run_id is not None

    with SessionLocal() as db:
        run = db.get(RetrievalRun, run_id)
        assert run is not None
        assert run.mode == "HYBRID"
        assert run.degradation_flags == []
        assert run.normalized_question == "T90000 的 CPU 和内存是什么？"
        assert run.query_texts == ["T90000 的 CPU 和内存是什么？"]
        assert run.evidence_status == "SUFFICIENT"
        assert run.candidate_counts["fused"] >= 1
        assert run.config_revision is not None
        assert run.params_snapshot["rrf_k"] == 60

        cands = db.execute(
            select(RetrievalCandidate).where(
                RetrievalCandidate.retrieval_run_id == run_id
            ).order_by(RetrievalCandidate.rank)
        ).scalars().all()
        assert len(cands) >= 1
        # (run_id, chunk_id) 唯一：无重复 chunk
        chunk_ids = [c.chunk_id for c in cands]
        assert len(chunk_ids) == len(set(chunk_ids))
        # 每个候选有分数明细；证据候选带 evidence_rank
        evidence_rows = [c for c in cands if c.is_evidence]
        assert evidence_rows
        assert all(c.rrf_score is not None for c in cands)
        assert all(c.rerank_score is not None for c in cands if c.rerank_score or c.is_evidence)


def test_product_and_doc_type_filter_narrows_evidence() -> None:
    with SessionLocal() as db:
        adapter = FakeSearchAdapter()
        cat, spec_doc, wp_doc = _seed_full(db, adapter)
        svc = _service(adapter)

        result = svc.retrieve(
            db,
            "吞吐量 内存 磁盘 网桥 路由 部署 引擎 检测",
            RetrievalFilters(product_id=cat["product"].id, document_type_ids=[cat["spec"].id]),
        )
        assert result.evidence
        # 只来自 product-spec 来源
        assert all(ev.source_id == spec_doc.source.id for ev in result.evidence)


def test_stale_superseded_version_in_index_not_recalled() -> None:
    """AC-RAG-001：旧版本即使索引残留也不召回。"""
    from sqlalchemy import text

    with SessionLocal() as db:
        adapter = FakeSearchAdapter()
        cat, spec_doc, wp_doc = _seed_full(db, adapter)
        # 把 spec 来源置为 OFFLINE 但索引仍保留（模拟异步下线滞后）
        db.execute(
            text("UPDATE knowledge.knowledge_sources SET status='OFFLINE' WHERE id=:sid"),
            {"sid": spec_doc.source.id},
        )
        db.commit()
        svc = _service(adapter)

        result = svc.retrieve(db, "E3800 吞吐量 内存 磁盘 网桥 路由 引擎 检测")
        assert all(ev.source_id != spec_doc.source.id for ev in result.evidence)


def test_embedding_failure_degrades_to_bm25_only() -> None:
    with SessionLocal() as db:
        adapter = FakeSearchAdapter()
        _seed_full(db, adapter)

        def failing_embed(db, query):
            raise GatewayError("NETWORK", "TIMEOUT", "查询向量化超时", retryable=True)

        svc = _service(adapter, embed=failing_embed)
        result = svc.retrieve(db, "E3800 的防病毒吞吐量是多少？")

        assert result.mode == "BM25_ONLY"
        assert "EMBEDDING_FAILED" in result.degradation_flags
        assert result.evidence  # BM25 仍召回
        assert "E3800" in result.evidence[0].content or "吞吐" in result.evidence[0].content


def test_vector_search_failure_degrades_to_bm25_only() -> None:
    class VectorFailAdapter(FakeSearchAdapter):
        def search(self, *, query_text=None, embedding=None, retrieval_type, top_k, version_ids=None):
            if retrieval_type == "vector":
                raise SearchAdapterError("PROVIDER", "SEARCH_503", "向量检索不可用", retryable=True)
            return super().search(
                query_text=query_text, embedding=embedding, retrieval_type=retrieval_type,
                top_k=top_k, version_ids=version_ids,
            )

    with SessionLocal() as db:
        adapter = VectorFailAdapter()
        _seed_full(db, adapter)
        svc = _service(adapter)
        result = svc.retrieve(db, "E3800 的防病毒吞吐量是多少？")

        assert result.mode == "BM25_ONLY"
        assert "VECTOR_SEARCH_FAILED" in result.degradation_flags
        assert result.evidence


def test_rerank_failure_falls_back_to_rrf_order() -> None:
    with SessionLocal() as db:
        adapter = FakeSearchAdapter()
        _seed_full(db, adapter)

        def failing_rerank(db, query, documents, top_n):
            raise GatewayError("PROVIDER", "PROVIDER_500", "重排服务异常", retryable=True)

        svc = _service(adapter, rerank=failing_rerank)
        result = svc.retrieve(db, "E3800 的防病毒吞吐量是多少？")

        assert "RERANK_FAILED" in result.degradation_flags
        assert result.evidence
        # 降级后用 RRF 顺序：分数单调不增
        scores = [ev.score_details["rrf_score"] for ev in result.evidence]
        assert scores == sorted(scores, reverse=True)


def test_rerank_ordering_applied_to_evidence() -> None:
    with SessionLocal() as db:
        adapter = FakeSearchAdapter()
        cat, spec_doc, wp_doc = _seed_full(db, adapter)
        svc = _service(adapter, rerank=_reverse_rerank)

        result = svc.retrieve(db, "吞吐量 内存 磁盘 网桥 路由 引擎 检测 内容")
        assert result.ordered_candidates
        # 注入的 rerank 按 (index+1) 降序 → 融合输入的最后候选排在首位
        assert result.evidence[0].content == result.ordered_candidates[0].doc.get("content")
        assert result.evidence[0].score_details["rerank_score"] is not None


def test_bm25_failure_records_failed_run_and_raises() -> None:
    class BM25FailAdapter(FakeSearchAdapter):
        def search(self, *, query_text=None, embedding=None, retrieval_type, top_k, version_ids=None):
            if retrieval_type == "bm25":
                raise SearchAdapterError("PROVIDER", "SEARCH_503", "BM25 检索不可用", retryable=True)
            return super().search(
                query_text=query_text, embedding=embedding, retrieval_type=retrieval_type,
                top_k=top_k, version_ids=version_ids,
            )

    with SessionLocal() as db:
        adapter = BM25FailAdapter()
        _seed_full(db, adapter)
        svc = _service(adapter)

        with pytest.raises(RetrievalError) as exc:
            svc.retrieve(db, "E3800 的吞吐量是多少？")
        assert exc.value.code == "SEARCH_BM25_FAILED"

    with SessionLocal() as db:
        from app.db.models.conversation import RetrievalRun

        run = db.execute(
            select(RetrievalRun).order_by(RetrievalRun.created_at.desc())
        ).scalars().first()
        assert run is not None
        assert run.status == "FAILED"
        assert run.mode == "FAILED"
        assert "BM25_FAILED" in run.degradation_flags
        assert run.error_code == "SEARCH_BM25_FAILED"


def test_no_queryable_documents_returns_insufficient_without_external_calls() -> None:
    with SessionLocal() as db:
        adapter = FakeSearchAdapter()  # 空索引
        calls = {"embed": 0, "rerank": 0}

        def counting_embed(db, query):
            calls["embed"] += 1
            return _embed_outcome(query)

        def counting_rerank(db, query, documents, top_n):
            calls["rerank"] += 1
            return _fake_rerank(db, query, documents, top_n)

        svc = _service(adapter, embed=counting_embed, rerank=counting_rerank)
        result = svc.retrieve(db, "任何问题都查不到资料")

        assert result.evidence == []
        assert result.evidence_status == "INSUFFICIENT"
        assert calls["embed"] == 0 and calls["rerank"] == 0
