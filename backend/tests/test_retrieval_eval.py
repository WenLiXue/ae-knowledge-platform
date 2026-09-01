"""黄金问题检索评测测试（DD-19 §18.3，Phase 5）。

验证：黄金集 CSV 解析、来源匹配、Recall@K/MRR/证据 Precision/旧版本误召回率计算、
系统行为/待入库题跳过、报告 JSON/Markdown 可保存。
"""

from __future__ import annotations

import json

import pytest

from app.db.session import SessionLocal
from app.retrieval.eval import (
    _title_match,
    evaluate,
    load_golden,
    report_to_dict,
    report_to_markdown,
    save_report,
)
from app.retrieval.service import _format_rerank_document
from app.retrieval.service import RetrievalService
from app.search.fake import FakeSearchAdapter

from _seed_retrieval import add_document, make_embedding, seed_catalog

GOLDEN_CSV = """case_id,status,category,question_type,user_question,expected_behavior,expected_key_points,required_source,source_location,forbidden_claims
KQ-EVAL-01,confirmed,硬件规格,spec_fact,E3800 的吞吐量和内存是多少？,answer,3.5G 15G 64G,AE 硬件规格,E3800 行,不得混用
KQ-EVAL-02,confirmed,白皮书,product_overview,信舷防毒墙 V7.0 是什么产品？,answer,下一代内容安全网关,V7.0 产品白皮书,3.1,不得扩展
KQ-EVAL-03,needs_business_review,SEG案件,case_retrieval,白云机场案件,answer,...,白云机场SEG案件原始记录,待入库,不得改写
KQ-EVAL-04,confirmed,系统行为,clarification,哪款设备最适合客户？,clarify,...,业务规则,澄清规则,不得直接推荐
"""


@pytest.mark.parametrize(
    ("required_source", "display_name"),
    [
        ("AE硬件型号规格", "AE硬件型号规格"),
        ("AE各版本补丁下载链接", "【AE】各版本（补丁）下载链接"),
        ("台山核电G680访问卡顿定位报告", "【台山核电】G680访问卡顿定位报告"),
        ("金华公安设备资源分析", "金华公安设备资源分析"),
        ("产品FAQ", "[信舷防毒墙系统]_AE_产品常见问题（FAQ）  (1).docx"),
        ("V7.0.0.2.2800部署指南", "亚信安全 信舷防毒墙系统 V7.0.0.2.2800_部署指南.pdf"),
    ],
)
def test_title_match_accepts_real_imported_names(required_source: str, display_name: str) -> None:
    assert _title_match(required_source, display_name)


def test_title_match_rejects_different_documents() -> None:
    assert not _title_match("产品FAQ", "V7.0.0.2.2800部署指南.pdf")


def test_rerank_document_keeps_structured_context() -> None:
    formatted = _format_rerank_document(
        {
            "title": "部署指南",
            "heading_path": ["升级", "主线版本"],
            "product_code": "AE",
            "product_version_code": "7.0.0.2.2800",
            "document_type_code": "DEPLOYMENT",
            "content": "先检查当前版本",
        }
    )
    assert "Title: 部署指南" in formatted
    assert "Section: 升级 > 主线版本" in formatted
    assert "Version: 7.0.0.2.2800" in formatted
    assert "Content: 先检查当前版本" in formatted


def _fake_embed(db, query: str):
    from app.retrieval.service import EmbedOutcome

    return EmbedOutcome(embedding=make_embedding(query), model_key="fake-embed")


def _fake_rerank(db, query: str, documents: list[str], top_n: int):
    from app.retrieval.service import RerankOutcome

    qv = make_embedding(query)
    scored = []
    for i, doc in enumerate(documents):
        dv = make_embedding(doc)
        dot = sum(a * b for a, b in zip(qv, dv))
        na = (sum(a * a for a in qv)) ** 0.5
        nb = (sum(a * a for a in dv)) ** 0.5
        scored.append((i, dot / (na * nb) if na and nb else 0.0))
    scored.sort(key=lambda item: item[1], reverse=True)
    return RerankOutcome(results=scored[:top_n], model_key="fake-rerank")


def _seed(tmp_path) -> None:
    (tmp_path / "golden.csv").write_text(GOLDEN_CSV, encoding="utf-8")
    with SessionLocal() as db:
        cat = seed_catalog(db)
        adapter = FakeSearchAdapter()
        add_document(
            db, adapter, display_name="AE 硬件规格", doc_type=cat["spec"],
            product=cat["product"], product_version=cat["product_version"],
            chunks=["E3800 防病毒吞吐量 3.5G 物理吞吐量 15G 内存 64G DDR4",
                    "T90000 CPU AMD EPYC 7H12 内存 256GB 磁盘 16TB"],
        )
        add_document(
            db, adapter, display_name="V7.0 产品白皮书", doc_type=cat["wp"],
            product=cat["product"], product_version=cat["product_version"],
            chunks=["信舷防毒墙是下一代内容安全网关 集成自研引擎 威胁情报 高性能流扫描",
                    "支持网桥模式 路由模式 反向代理模式"],
        )
        db.commit()
    return adapter


def test_golden_parse_and_metrics(tmp_path) -> None:
    adapter = _seed(tmp_path)
    cases = load_golden(tmp_path / "golden.csv")
    assert len(cases) == 4
    assert cases[0].case_id == "KQ-EVAL-01"

    with SessionLocal() as db:
        svc = RetrievalService(search=adapter, embed_fn=_fake_embed, rerank_fn=_fake_rerank)
        report = evaluate(db, svc, cases)

    assert report.total == 4
    assert report.executed == 2
    assert report.skipped == 2
    assert report.recall_at_k == 1.0
    assert report.mrr > 0
    assert report.evidence_precision >= 0.5
    assert report.stale_version_recall_rate == 0.0

    by_id = {c.case_id: c for c in report.cases}
    assert not by_id["KQ-EVAL-01"].skipped and by_id["KQ-EVAL-01"].recall_at_k
    assert by_id["KQ-EVAL-01"].mrr > 0
    assert not by_id["KQ-EVAL-02"].skipped and by_id["KQ-EVAL-02"].recall_at_k
    assert by_id["KQ-EVAL-03"].skipped  # 待入库
    assert by_id["KQ-EVAL-04"].skipped  # 业务规则


def test_report_saved_as_json_and_markdown(tmp_path) -> None:
    adapter = _seed(tmp_path)
    cases = load_golden(tmp_path / "golden.csv")
    with SessionLocal() as db:
        svc = RetrievalService(search=adapter, embed_fn=_fake_embed, rerank_fn=_fake_rerank)
        report = evaluate(db, svc, cases)

    json_path = save_report(report, tmp_path / "report.json")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["summary"]["recall_at_k"] == 1.0
    assert len(data["cases"]) == 4

    md = report_to_markdown(report)
    assert "Recall@K" in md and "KQ-EVAL-01" in md
    md_path = save_report(report, tmp_path / "report.md", as_markdown=True)
    assert md_path.read_text(encoding="utf-8").startswith("# ")

    # 序列化往返
    dumped = report_to_dict(report)
    assert dumped["summary"]["stale_version_recall_rate"] == 0.0
