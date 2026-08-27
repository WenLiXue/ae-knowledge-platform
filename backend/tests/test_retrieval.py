"""检索核心纯函数、配置与过滤测试（DD-19 §12，Phase 5）。

覆盖：
- RRF 融合公式、相邻同节去重、最终排序（Rerank 优先）；
- 证据选择：数量上限 / token 预算 / 每来源上限；
- retrieval 配置默认值与 ACTIVE revision 覆盖；
- 过滤校验（ID 必须来自数据库、版本属于产品）与可查询版本解析（AC-RAG-001/002）。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.db.models.catalog import Product, ProductVersion
from app.db.models.config import ConfigRevision
from app.db.session import SessionLocal
from app.retrieval.config import load_retrieval_config
from app.retrieval.core import (
    Candidate,
    dedupe_adjacent,
    evidence_status,
    rrf_fuse,
    select_evidence,
    sort_final,
)
from app.retrieval.errors import RetrievalError
from app.retrieval.filters import resolve_active_versions, validate_filters
from app.retrieval.query_plan import build_query_plan
from app.retrieval.schemas import RetrievalFilters
from app.search.fake import FakeSearchAdapter

from _seed_retrieval import SYSTEM_USER, add_document, seed_catalog


# ---- 核心纯函数 ----

def _cand(cid: str, *, source_id="s1", version_id="v1", heading=None, ordinal=None,
          content="正文内容", rrf=1.0, token_count=None) -> Candidate:
    doc = {
        "content": content,
        "heading_path": heading or [],
        "ordinal": ordinal,
        "token_count": token_count if token_count is not None else max(1, len(content) // 3),
    }
    return Candidate(chunk_id=cid, source_id=source_id, version_id=version_id, doc=doc, rrf_score=rrf)


def test_rrf_fuse_formula() -> None:
    # chunk a 只在 bm25 rank1；chunk b 在 bm25 rank2 + vector rank1
    fused = rrf_fuse({"a": 1, "b": 2}, {"b": 1, "c": 3}, k=60)
    assert abs(fused["a"] - 1 / 61) < 1e-9
    assert abs(fused["b"] - (1 / 62 + 1 / 61)) < 1e-9
    assert abs(fused["c"] - 1 / 63) < 1e-9


def test_dedupe_adjacent_same_section_keeps_higher() -> None:
    # 同来源相邻 ordinal、同 heading_path → 保留 RRF 高者
    high = _cand("c1", ordinal=1, heading=["章节A"], rrf=0.5)
    low = _cand("c2", ordinal=2, heading=["章节A"], rrf=0.3)
    other = _cand("c3", ordinal=1, heading=["章节B"], rrf=0.1)
    kept = dedupe_adjacent([low, high, other])
    ids = [c.chunk_id for c in kept]
    assert ids == ["c1", "c3"]


def test_dedupe_adjacent_different_section_kept() -> None:
    a = _cand("a", ordinal=1, heading=["X"])
    b = _cand("b", ordinal=2, heading=["Y"])
    assert [c.chunk_id for c in dedupe_adjacent([a, b])] == ["a", "b"]


def test_sort_final_rerank_preferred_over_rrf() -> None:
    low_rrf_rerank_high = _cand("a", rrf=0.1)
    low_rrf_rerank_high.rerank_score = 0.9
    high_rrf_no_rerank = _cand("b", rrf=0.5)
    ordered = sort_final([high_rrf_no_rerank, low_rrf_rerank_high])
    assert [c.chunk_id for c in ordered] == ["a", "b"]


def test_select_evidence_evidence_max() -> None:
    cands = [_cand(f"c{i}", source_id="s1", ordinal=i, heading=["H"]) for i in range(1, 6)]
    kept = select_evidence(cands, evidence_min=1, evidence_max=3, evidence_token_budget=10_000, per_source_limit=10)
    assert len(kept) == 3
    assert [c.chunk_id for c in kept] == ["c1", "c2", "c3"]
    assert cands[3].exclusion_reason == "EVIDENCE_MAX"


def test_select_evidence_per_source_limit() -> None:
    cands = [
        _cand("a1", source_id="s1", ordinal=1, heading=["H"]),
        _cand("a2", source_id="s1", ordinal=2, heading=["H"]),
        _cand("b1", source_id="s2", ordinal=1, heading=["H"]),
    ]
    kept = select_evidence(cands, evidence_min=1, evidence_max=5, evidence_token_budget=10_000, per_source_limit=1)
    assert [c.chunk_id for c in kept] == ["a1", "b1"]
    assert cands[1].exclusion_reason == "PER_SOURCE_LIMIT"


def test_select_evidence_token_budget() -> None:
    cands = [_cand("c1", content="短", token_count=10), _cand("c2", content="长", token_count=1000)]
    kept = select_evidence(cands, evidence_min=1, evidence_max=5, evidence_token_budget=500, per_source_limit=10)
    assert [c.chunk_id for c in kept] == ["c1"]
    assert cands[1].exclusion_reason == "TOKEN_BUDGET"


def test_evidence_status_thresholds() -> None:
    assert evidence_status(4, 4) == "SUFFICIENT"
    assert evidence_status(2, 4) == "PARTIAL"
    assert evidence_status(0, 4) == "INSUFFICIENT"


# ---- 配置 ----

def test_retrieval_config_defaults() -> None:
    with SessionLocal() as db:
        cfg = load_retrieval_config(db)
        assert cfg.config_revision == 0
        assert cfg.bm25_top_k == 50
        assert cfg.rrf_k == 60
        assert cfg.rerank_min_score == 0.2
        assert cfg.evidence_min == 4 and cfg.evidence_max == 8


def test_retrieval_config_from_active_revision() -> None:
    with SessionLocal() as db:
        db.add(
            ConfigRevision(
                namespace="retrieval",
                content={
                    "schema_version": "1",
                    "bm25_top_k": 10,
                    "vector_top_k": 12,
                    "rrf_k": 30,
                    "rerank_min_score": 0.2,
                    "evidence_max": 6,
                },
                status="ACTIVE",
                created_by_user_id=uuid.UUID(SYSTEM_USER),
            )
        )
        db.commit()
    with SessionLocal() as db:
        cfg = load_retrieval_config(db)
        assert cfg.bm25_top_k == 10
        assert cfg.vector_top_k == 12
        assert cfg.rrf_k == 30
        assert cfg.rerank_min_score == 0.2
        # evidence_min 被夹紧不超过 evidence_max
        assert cfg.evidence_min <= cfg.evidence_max == 6
        assert cfg.config_revision is not None


# ---- 过滤与可查询版本 ----

def _seed_base(db):
    cat = seed_catalog(db)
    adapter = FakeSearchAdapter()
    spec_doc = add_document(
        db, adapter,
        display_name="AE 硬件规格", doc_type=cat["spec"], product=cat["product"],
        product_version=cat["product_version"],
        chunks=["E3800 防病毒吞吐量 3.5G 物理吞吐量 15G 内存 64G",
                "T90000 CPU AMD EPYC 7H12 内存 256GB 磁盘 16TB"],
    )
    wp_doc = add_document(
        db, adapter,
        display_name="V7.0 产品白皮书", doc_type=cat["wp"], product=cat["product"],
        product_version=cat["product_version"],
        chunks=["信舷防毒墙是下一代内容安全网关 支持网桥模式"],
    )
    db.commit()
    return cat, adapter, spec_doc, wp_doc


def test_validate_filters_rejects_unknown_ids() -> None:
    with SessionLocal() as db:
        _seed_base(db)
        with pytest.raises(RetrievalError) as exc:
            validate_filters(db, RetrievalFilters(product_id=uuid.uuid4()))
        assert exc.value.code == "FILTER_PRODUCT_NOT_FOUND"

        with pytest.raises(RetrievalError) as exc:
            validate_filters(db, RetrievalFilters(version_ids=[uuid.uuid4()]))
        assert exc.value.code == "FILTER_VERSION_NOT_FOUND"


def test_validate_filters_version_must_belong_to_product() -> None:
    with SessionLocal() as db:
        cat = seed_catalog(db)
        other_product = Product(code="OTHER", name="其他产品", sort_order=2)
        db.add(other_product)
        db.flush()
        other_version = ProductVersion(product_id=other_product.id, version_code="V1.0", sort_order=0)
        db.add(other_version)
        db.flush()
        db.commit()
        with pytest.raises(RetrievalError) as exc:
            validate_filters(
                db, RetrievalFilters(product_id=cat["product"].id, version_ids=[other_version.id])
            )
        assert exc.value.code == "FILTER_VERSION_PRODUCT_MISMATCH"


def test_resolve_active_versions_only_queryable_current_generation() -> None:
    """AC-RAG-001：只召回 QUERYABLE 的 current_version / 当前 generation。"""
    with SessionLocal() as db:
        cat, adapter, spec_doc, wp_doc = _seed_base(db)
        # 下线/待确认/旧版本即使仍留在索引中也绝不召回
        offline_doc = add_document(
            db, adapter,
            display_name="已下线来源", doc_type=cat["spec"], product=cat["product"],
            product_version=cat["product_version"], chunks=["旧内容不应当被召回"],
            status_source="OFFLINE",
        )
        pending_doc = add_document(
            db, adapter,
            display_name="待确认来源", doc_type=cat["spec"], product=cat["product"],
            product_version=cat["product_version"], chunks=["待确认不应当被召回"],
            status_source="PENDING_CONFIRMATION",
        )
        db.commit()

        refs = resolve_active_versions(db)
        version_ids = {str(r.version_id) for r in refs}
        assert str(spec_doc.version.id) in version_ids
        assert str(wp_doc.version.id) in version_ids
        assert str(offline_doc.version.id) not in version_ids
        assert str(pending_doc.version.id) not in version_ids
        for ref in refs:
            assert ref.generation  # index_generation 非空


def test_resolve_active_versions_superseded_version_excluded() -> None:
    """旧 current_version 被替换后即使索引残留也不召回。"""
    with SessionLocal() as db:
        cat, adapter, spec_doc, wp_doc = _seed_base(db)
        # 把 spec_doc 版本标记 SUPERSEDED 并从来源切走 current_version_id
        db.execute(
            text(
                "UPDATE knowledge.knowledge_sources SET current_version_id=NULL "
                "WHERE id=:sid"
            ),
            {"sid": spec_doc.source.id},
        )
        db.execute(
            text("UPDATE knowledge.document_versions SET status='SUPERSEDED' WHERE id=:vid"),
            {"vid": spec_doc.version.id},
        )
        db.commit()
        refs = resolve_active_versions(db)
        assert str(spec_doc.version.id) not in {str(r.version_id) for r in refs}
        assert str(wp_doc.version.id) in {str(r.version_id) for r in refs}


def test_resolve_active_versions_filters_narrow() -> None:
    """AC-RAG-002：页面产品/版本/文档类型条件真实进入过滤。"""
    with SessionLocal() as db:
        cat, adapter, spec_doc, wp_doc = _seed_base(db)

        spec_filter = resolve_active_versions(
            db, RetrievalFilters(product_id=cat["product"].id, document_type_ids=[cat["spec"].id])
        )
        assert {str(r.version_id) for r in spec_filter} == {str(spec_doc.version.id)}

        wp_filter = resolve_active_versions(
            db, RetrievalFilters(product_id=cat["product"].id, document_type_ids=[cat["wp"].id])
        )
        assert {str(r.version_id) for r in wp_filter} == {str(wp_doc.version.id)}

        # 空结果不自动放宽（DD-07 §7.3）：合法条件但无匹配文档 → 空，不报错
        other_product = Product(code="OTHER", name="其他产品", sort_order=2)
        db.add(other_product)
        db.flush()
        db.commit()
        empty_filter = resolve_active_versions(db, RetrievalFilters(product_id=other_product.id))
        assert empty_filter == []


def test_build_query_plan_validates_and_assembles() -> None:
    with SessionLocal() as db:
        cat = seed_catalog(db)
        db.commit()
        plan = build_query_plan(db, "E3800 的吞吐量是多少？")
        assert plan.normalized_question == "E3800 的吞吐量是多少？"
        assert plan.query_texts == ["E3800 的吞吐量是多少？"]
        assert plan.operation == "ANSWER"

        with pytest.raises(RetrievalError) as exc:
            build_query_plan(db, "   ")
        assert exc.value.code == "EMPTY_QUESTION"

        with pytest.raises(RetrievalError) as exc:
            build_query_plan(db, "x", RetrievalFilters(product_id=uuid.uuid4()))
        assert exc.value.code == "FILTER_PRODUCT_NOT_FOUND"
