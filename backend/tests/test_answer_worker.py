"""Answer Worker 测试（DD-08 §11、DD-10 §3-4，Phase 6）。

覆盖：
- 真实生成路径（feature_real_qa=True + 注入 chat_fn）：理解→检索→生成→引用快照→SUCCEEDED；
- 需澄清 → CLARIFICATION；
- 理解失败 → QUERY_REWRITE_FAILED 降级原问题仍生成；
- 无证据 → INSUFFICIENT，不调用生成模型；
- 检索失败 → Answer FAILED + PipelineError；
- 取消 → CANCELED。
"""

from __future__ import annotations

import json

import pytest

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.model_gateway.errors import GatewayError
from app.search.base import SearchAdapterError
from app.search.fake import FakeSearchAdapter
from app.worker.pipeline import PipelineError

from _seed_retrieval import (
    add_document,
    make_user,
    run_answer_task,
    seed_catalog,
    user_cookies,
)
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def _seed(adapter: FakeSearchAdapter, *, with_docs: bool = True):
    with SessionLocal() as s:
        cat = seed_catalog(s)
        if with_docs:
            add_document(
                s, adapter, display_name="AE 硬件规格", doc_type=cat["spec"],
                product=cat["product"], product_version=cat["product_version"],
                chunks=["T90000 CPU AMD EPYC 7H12 内存 256GB 磁盘 16TB",
                        "E3800 防病毒吞吐量 3.5G 内存 64G DDR4"],
            )
        s.commit()
        user = make_user(s, display_name="问答用户")
        cookies = user_cookies(s, user)
        s.commit()
    return cookies


def _ask(cookies, content="T90000 的内存是多少？") -> dict:
    resp = client.post("/api/v1/conversations", json={"title": "问答"}, cookies=cookies)
    assert resp.status_code == 201, resp.text
    conv = resp.json()["data"]
    resp = client.post(
        f"/api/v1/conversations/{conv['id']}/messages",
        json={"content": content},
        cookies=cookies,
    )
    assert resp.status_code == 202, resp.text
    return resp.json()["data"]


def _get_answer(answer_id, cookies) -> dict:
    return client.get(f"/api/v1/answers/{answer_id}", cookies=cookies).json()["data"]


def _dual_chat(messages):
    """理解 vs 生成双角色假模型：按 user 消息是否含 <evidence> 区分。"""
    content = messages[-1]["content"]
    if "<evidence>" in content:
        return json.dumps(
            {
                "answer_type": "ANSWER",
                "summary": "T90000 配置 256GB 内存。",
                "blocks": [
                    {"type": "paragraph", "content": "T90000 内存为 256GB。", "citation_ids": ["E1"]}
                ],
                "follow_up_suggestions": [],
            }
        )
    return json.dumps(
        {
            "standalone_query": "T90000 的内存规格是多少？",
            "detected_entities": [{"entity_type": "model", "value": "T90000"}],
            "intent_hint": None,
            "clarification_needed": False,
            "clarification_question": None,
            "reason_code": None,
        }
    )


def test_real_generation_path_succeeds_with_citations(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "feature_real_qa", True)
    adapter = FakeSearchAdapter()
    cookies = _seed(adapter)
    result = _ask(cookies)

    run_answer_task(adapter, answer_id=result["answer_id"], chat_fn=_dual_chat)

    answer = _get_answer(result["answer_id"], cookies)
    assert answer["status"] == "SUCCEEDED"
    assert answer["answer_type"] == "ANSWER"
    assert answer["summary"] == "T90000 配置 256GB 内存。"
    assert answer["blocks"][0]["citation_nos"] == [1]
    assert answer["citations"][0]["document_title"] == "AE 硬件规格"


def test_clarification_when_understanding_needs_more(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "feature_real_qa", True)
    adapter = FakeSearchAdapter()
    cookies = _seed(adapter)

    def clarify_chat(messages):
        return json.dumps(
            {
                "standalone_query": "",
                "detected_entities": [],
                "intent_hint": None,
                "clarification_needed": True,
                "clarification_question": "请补充吞吐量要求与接口类型。",
                "reason_code": "MISSING_CONSTRAINTS",
            }
        )

    result = _ask(cookies)
    run_answer_task(adapter, answer_id=result["answer_id"], chat_fn=clarify_chat)
    answer = _get_answer(result["answer_id"], cookies)
    assert answer["status"] == "SUCCEEDED"
    assert answer["answer_type"] == "CLARIFICATION"
    assert "补充" in (answer["summary"] or "")


def test_chat_intent_skips_rag_retrieval(monkeypatch) -> None:
    """主 Agent 判定闲聊后，不应触发 BM25/向量检索。"""
    monkeypatch.setattr(get_settings(), "feature_real_qa", True)

    class NoSearchAdapter(FakeSearchAdapter):
        def search(self, **kwargs):
            raise AssertionError("CHAT 意图不应调用 RAG")

    adapter = NoSearchAdapter()
    cookies = _seed(adapter)

    def chat(messages):
        content = messages[-1]["content"]
        if messages[0]["content"].startswith("你是企业知识智能助手"):
            return json.dumps(
                {
                    "answer_type": "ANSWER",
                    "summary": "你好！我是知识智能助手。",
                    "blocks": [],
                    "follow_up_suggestions": [],
                }
            )
        assert "问题：你好" in content
        return json.dumps(
            {
                "operation": "CHAT",
                "standalone_query": "你好",
                "detected_entities": [],
                "intent_hint": "greeting",
                "clarification_needed": False,
                "clarification_question": None,
                "reason_code": None,
            }
        )

    result = _ask(cookies, content="你好")
    run_answer_task(adapter, answer_id=result["answer_id"], chat_fn=chat)
    answer = _get_answer(result["answer_id"], cookies)
    assert answer["status"] == "SUCCEEDED"
    assert answer["summary"] == "你好！我是知识智能助手。"
    assert answer["citations"] == []
    assert "NO_KNOWLEDGE_RETRIEVAL" in answer["degradation_flags"]


def test_understanding_failure_degrades_with_flag(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "feature_real_qa", True)
    adapter = FakeSearchAdapter()
    cookies = _seed(adapter)

    def understand_boom(messages):
        content = messages[-1]["content"]
        if "<evidence>" in content:
            return _dual_chat(messages)  # 生成正常
        raise GatewayError("NETWORK", "TIMEOUT", "理解模型超时", retryable=True)

    result = _ask(cookies)
    run_answer_task(adapter, answer_id=result["answer_id"], chat_fn=understand_boom)
    answer = _get_answer(result["answer_id"], cookies)
    assert answer["status"] == "SUCCEEDED"
    assert "QUERY_REWRITE_FAILED" in answer["degradation_flags"]


def test_no_evidence_returns_insufficient_without_model_call(monkeypatch) -> None:
    # 空索引 → 无证据 → INSUFFICIENT；注入会失败的 chat_fn 证明不调用生成模型
    adapter = FakeSearchAdapter()
    cookies = _seed(adapter, with_docs=False)

    def boom(messages):
        raise AssertionError("不应调用生成模型")

    result = _ask(cookies)
    run_answer_task(adapter, answer_id=result["answer_id"], chat_fn=boom)
    answer = _get_answer(result["answer_id"], cookies)
    assert answer["status"] == "SUCCEEDED"
    assert answer["answer_type"] == "INSUFFICIENT"
    assert answer["blocks"] == []
    assert answer["citations"] == []


def test_retrieval_failure_marks_answer_failed() -> None:
    class BM25FailAdapter(FakeSearchAdapter):
        def search(self, *, query_text=None, embedding=None, retrieval_type, top_k, version_ids=None):
            if retrieval_type == "bm25":
                raise SearchAdapterError("PROVIDER", "SEARCH_503", "BM25 检索不可用", retryable=True)
            return super().search(
                query_text=query_text, embedding=embedding, retrieval_type=retrieval_type,
                top_k=top_k, version_ids=version_ids,
            )

    adapter = BM25FailAdapter()
    cookies = _seed(adapter)
    result = _ask(cookies)

    with pytest.raises(PipelineError) as exc:
        run_answer_task(adapter, answer_id=result["answer_id"])
    assert exc.value.code == "SEARCH_BM25_FAILED"

    answer = _get_answer(result["answer_id"], cookies)
    assert answer["status"] == "FAILED"
    assert answer["error_code"] == "SEARCH_BM25_FAILED"


def test_cancel_before_run_marks_canceled() -> None:
    adapter = FakeSearchAdapter()
    cookies = _seed(adapter)
    result = _ask(cookies)
    assert client.post(f"/api/v1/answers/{result['answer_id']}/cancel", cookies=cookies).status_code == 200

    run_answer_task(adapter, answer_id=result["answer_id"])
    answer = _get_answer(result["answer_id"], cookies)
    assert answer["status"] == "CANCELED"
