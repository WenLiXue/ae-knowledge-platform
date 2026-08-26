"""Agent 策略/记忆/引用 单元测试（DD-21 TC-LG-003/006/007/008/009/010）。"""

from __future__ import annotations

import datetime

import pytest

from app.agent.citations import validate_citation_drafts
from app.agent.context import AgentRuntimeContext, TokenEstimator, build_context
from app.agent.memory import compute_context_budget, parse_memory_patch
from app.agent.policies import local_requires_retrieval
from app.core.config import get_settings


def _ctx() -> AgentRuntimeContext:
    settings = get_settings()
    return build_context(
        settings=settings,
        clock=lambda: datetime.datetime.now(datetime.timezone.utc),
    )


# ---- TC-LG-003：一般 EXPLAIN 可不检索；带产品实体必须检索 ----

def test_general_explain_does_not_retrieve():
    requires, reason = local_requires_retrieval(
        "EXPLAIN", query_entities=[], filters_snapshot={}, memory_entities=[]
    )
    assert requires is False
    assert reason == "GENERAL_EXPLAIN"


def test_explain_with_internal_entity_must_retrieve():
    requires, reason = local_requires_retrieval(
        "EXPLAIN",
        query_entities=[{"entity_type": "model", "value": "T90000"}],
        filters_snapshot={},
        memory_entities=[],
    )
    assert requires is True


def test_explain_with_filter_must_retrieve():
    requires, _ = local_requires_retrieval(
        "EXPLAIN",
        query_entities=[],
        filters_snapshot={"product_id": "00000000-0000-0000-0000-000000000001"},
        memory_entities=[],
    )
    assert requires is True


def test_answer_always_retrieves_even_if_model_says_no():
    requires, _ = local_requires_retrieval(
        "ANSWER", query_entities=[], filters_snapshot={}, memory_entities=[]
    )
    assert requires is True


def test_chat_never_retrieves():
    requires, _ = local_requires_retrieval(
        "CHAT",
        query_entities=[{"entity_type": "model", "value": "AE"}],
        filters_snapshot={},
        memory_entities=[],
    )
    assert requires is False


# ---- TC-LG-006：上下文预算 ----

def test_context_budget_within_window():
    ctx = _ctx()
    budget = compute_context_budget(ctx, "T90000 内存是多少？")
    assert budget["recent"] <= get_settings().conversation_recent_token_budget
    assert budget["summary"] <= get_settings().conversation_summary_token_budget
    assert budget["evidence"] > 0
    assert budget["recent"] + budget["summary"] + budget["evidence"] < budget["available"]


def test_token_estimator_deterministic():
    est = TokenEstimator()
    a = est.estimate("AE 信被防毒墙 V7.0 配置")
    assert a == est.estimate("AE 信被防毒墙 V7.0 配置")
    assert a > 0


# ---- TC-LG-008：非本轮 evidence 引用校验失败 ----

def test_citation_outside_evidence_fails():
    errors = validate_citation_drafts(
        blocks=[{"block_id": "b1", "type": "paragraph", "content": "x", "citation_nos": [1]}],
        citation_drafts=[{"chunk_id": "not-in-evidence", "original_url": "https://example.com/a"}],
        evidence=[{"chunk_id": "in-evidence", "evidence_id": "E1"}],
    )
    assert any("不属于本轮证据" in e for e in errors)


def test_citation_within_evidence_passes():
    errors = validate_citation_drafts(
        blocks=[{"block_id": "b1", "type": "paragraph", "content": "x", "citation_nos": [1]}],
        citation_drafts=[{"chunk_id": "in-evidence", "original_url": "https://example.com/a"}],
        evidence=[{"chunk_id": "in-evidence", "evidence_id": "E1"}],
    )
    assert errors == []


def test_fact_block_requires_citation():
    errors = validate_citation_drafts(
        blocks=[{"block_id": "b1", "type": "paragraph", "content": "x", "citation_nos": []}],
        citation_drafts=[],
        evidence=[{"chunk_id": "c1", "evidence_id": "E1"}],
    )
    assert any("缺少引用" in e for e in errors)


# ---- 记忆 Schema 解析 ----

def test_parse_memory_patch_valid():
    patch = parse_memory_patch(
        '```json\n{"summary": "用户询问 T90000 内存", "entities": [{"entity_type": "model", "value": "T90000"}], '
        '"constraints": ["只看V7.0"], "unresolved_topics": ["是否需要配置REST"]}\n```',
        TokenEstimator(),
    )
    assert patch["summary"]
    assert patch["entities"][0]["value"] == "T90000"
    assert patch["constraints"] == ["只看V7.0"]


def test_parse_memory_patch_invalid_raises():
    with pytest.raises(ValueError):
        parse_memory_patch("not json at all", TokenEstimator())
