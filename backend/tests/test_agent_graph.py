"""Agent 图集成测试（DD-21 TC-LG-101~112 子集，agent_graph_enabled=True）。

覆盖：问候不检索、内部产品问题检索+引用、澄清、无证据、取消、幂等重投、连续追问、
长会话压缩、引用校验、step limit。
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.db.models.conversation import AgentRun, ConversationMemory
from app.db.models.task import ProcessingTask
from app.main import app
from app.qa.worker import run_generate_answer
from app.search.fake import FakeSearchAdapter
from app.worker.pipeline import PipelineError

from _seed_retrieval import add_document, fake_retrieval_service, make_user, seed_catalog, user_cookies

client = TestClient(app)


def _enable(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "agent_graph_enabled", True)


def _seed(adapter: FakeSearchAdapter, *, with_docs: bool = True) -> dict:
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
        user = make_user(s, display_name="Agent 用户")
        cookies = user_cookies(s, user)
        s.commit()
    return cookies


def _ask(cookies, content: str = "T90000 的内存是多少？", conv_id=None):
    if conv_id is None:
        resp = client.post("/api/v1/conversations", json={"title": "Agent 问答"}, cookies=cookies)
        assert resp.status_code == 201, resp.text
        conv_id = resp.json()["data"]["id"]
    resp = client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"content": content},
        cookies=cookies,
    )
    assert resp.status_code == 202, resp.text
    data = resp.json()["data"]
    data["conversation_id"] = conv_id
    return data


def _get_answer(answer_id, cookies) -> dict:
    return client.get(f"/api/v1/answers/{answer_id}", cookies=cookies).json()["data"]


def _run_agent(adapter, *, answer_id, chat_fn=None, settings=None):
    with SessionLocal() as s:
        query = select(ProcessingTask).where(ProcessingTask.task_type == "GENERATE_ANSWER")
        query = query.where(ProcessingTask.payload["answer_id"].astext == str(answer_id))
        task = s.execute(query.order_by(ProcessingTask.created_at.desc()).limit(1)).scalars().first()
        assert task is not None, "未找到 GENERATE_ANSWER 任务"
        svc = fake_retrieval_service(adapter)
        return run_generate_answer(s, task, search=adapter, retrieval_service=svc, chat_fn=chat_fn, settings=settings)


# ---- TC-LG-101 问候：不调用知识库 ----

def test_greeting_does_not_retrieve(monkeypatch) -> None:
    _enable(monkeypatch)

    class NoSearchAdapter(FakeSearchAdapter):
        def search(self, **kwargs):
            raise AssertionError("问候意图不应触发检索")

    adapter = NoSearchAdapter()
    cookies = _seed(adapter)
    result = _ask(cookies, "你好")
    _run_agent(adapter, answer_id=result["answer_id"])
    answer = _get_answer(result["answer_id"], cookies)
    assert answer["status"] == "SUCCEEDED"
    assert answer["citations"] == []
    assert "NO_KNOWLEDGE_RETRIEVAL" in answer["degradation_flags"]


def test_greeting_prefixed_knowledge_question_retrieves(monkeypatch) -> None:
    """问候只是前缀时，仍应进入 knowledge.search。"""
    _enable(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "feature_real_qa", True)
    monkeypatch.setattr(settings, "agent_tools_enabled", True)
    monkeypatch.setattr(settings, "agent_planner_enabled", True)
    monkeypatch.setattr(settings, "agent_query_rewrite_limit", 0)

    def chat(messages):
        system = messages[0]["content"]
        user = messages[-1]["content"]
        if "目标理解器" in system:
            return json.dumps(
                {
                    "intent": "CHAT",
                    "operation": "CHAT",
                    "goal": "hello,T90000的内存是多少？",
                    "entities": [],
                    "constraints": [],
                    "completion_criteria": [],
                    "requires_enterprise_evidence": False,
                    "candidate_capabilities": [],
                    "ambiguity": [],
                    "risk_hint": "NONE",
                    "confidence": 0.99,
                }
            )
        if "<evidence>" in user:
            return json.dumps(
                {
                    "answer_type": "ANSWER",
                    "summary": "T90000 内存为 256GB。",
                    "blocks": [
                        {
                            "type": "paragraph",
                            "content": "T90000 内存为 256GB。",
                            "citation_ids": ["E1"],
                        }
                    ],
                    "follow_up_suggestions": [],
                }
            )
        return "{}"  # 规划器解析失败后使用确定性单工具回退

    adapter = FakeSearchAdapter()
    cookies = _seed(adapter)
    result = _ask(cookies, "hello,T90000的内存是多少？")
    _run_agent(adapter, answer_id=result["answer_id"], chat_fn=chat, settings=settings)
    answer = _get_answer(result["answer_id"], cookies)
    assert answer["status"] == "SUCCEEDED"
    assert answer["citations"]


def test_identity_uses_authenticated_context_without_retrieval(monkeypatch) -> None:
    """身份问题走运行时主体上下文，不进入 RAG 或工具计划。"""
    _enable(monkeypatch)
    monkeypatch.setattr(get_settings(), "feature_real_qa", True)

    class NoSearchAdapter(FakeSearchAdapter):
        def search(self, **kwargs):
            raise AssertionError("身份问题不应触发检索")

    def chat(messages):
        return json.dumps({
            "intent": "IDENTITY",
            "operation": "ANSWER",
            "goal": "查看当前登录主体身份",
            "entities": [],
            "constraints": [],
            "completion_criteria": [],
            "requires_enterprise_evidence": True,
            "candidate_capabilities": ["knowledge.search"],
            "ambiguity": [],
            "risk_hint": "READ_ONLY",
            "confidence": 0.99,
        })

    adapter = NoSearchAdapter()
    cookies = _seed(adapter)
    result = _ask(cookies, "我是谁？")
    _run_agent(adapter, answer_id=result["answer_id"], chat_fn=chat)
    answer = _get_answer(result["answer_id"], cookies)
    assert answer["status"] == "SUCCEEDED"
    assert answer["answer_type"] == "ANSWER"
    assert "Agent 用户" in (answer["summary"] or "")
    assert answer["citations"] == []

    with SessionLocal() as s:
        run = s.execute(
            select(AgentRun).where(AgentRun.answer_id == uuid.UUID(result["answer_id"]))
        ).scalars().first()
        assert run is not None and run.operation == "IDENTITY"


# ---- TC-LG-102 内部产品问题：检索 + 生成 + 引用 + 持久化 ----

def test_internal_question_retrieves_with_citations(monkeypatch) -> None:
    _enable(monkeypatch)
    adapter = FakeSearchAdapter()
    cookies = _seed(adapter)
    result = _ask(cookies, "T90000 的内存是多少？")
    _run_agent(adapter, answer_id=result["answer_id"])
    answer = _get_answer(result["answer_id"], cookies)
    assert answer["status"] == "SUCCEEDED"
    assert answer["answer_type"] == "ANSWER"
    assert answer["citations"], "应有来源引用"
    with SessionLocal() as s:
        run = s.execute(
            select(AgentRun).where(AgentRun.answer_id == uuid.UUID(result["answer_id"]))
        ).scalars().first()
        assert run is not None and run.status == "SUCCEEDED"
        assert run.checkpoint_thread_id == str(result["answer_id"])


# ---- TC-LG-103 输入不足：澄清，不检索 ----

def test_clarification_when_needs_more(monkeypatch) -> None:
    _enable(monkeypatch)
    monkeypatch.setattr(get_settings(), "feature_real_qa", True)
    adapter = FakeSearchAdapter()
    cookies = _seed(adapter)

    def chat(messages):
        return json.dumps(
            {
                "operation": "CLARIFY",
                "standalone_query": "",
                "detected_entities": [],
                "intent_hint": None,
                "clarification_needed": True,
                "clarification_question": "请补充吞吐量要求与接口类型。",
                "reason_code": "MISSING_CONSTRAINTS",
            }
        )

    result = _ask(cookies, "帮我看看怎么配置")
    _run_agent(adapter, answer_id=result["answer_id"], chat_fn=chat)
    answer = _get_answer(result["answer_id"], cookies)
    assert answer["status"] == "SUCCEEDED"
    assert answer["answer_type"] == "CLARIFICATION"
    assert "补充" in (answer["summary"] or "")


# ---- TC-LG-106 无证据：不生成内部事实 ----

def test_no_evidence_returns_insufficient(monkeypatch) -> None:
    _enable(monkeypatch)
    adapter = FakeSearchAdapter()
    cookies = _seed(adapter, with_docs=False)

    def boom(messages):
        raise AssertionError("无证据不应调用生成模型")

    result = _ask(cookies)
    _run_agent(adapter, answer_id=result["answer_id"], chat_fn=boom)
    answer = _get_answer(result["answer_id"], cookies)
    assert answer["status"] == "SUCCEEDED"
    assert answer["answer_type"] == "INSUFFICIENT"
    assert answer["citations"] == []


# ---- TC-LG-109 用户取消 ----

def test_cancel_before_run_marks_canceled(monkeypatch) -> None:
    _enable(monkeypatch)
    adapter = FakeSearchAdapter()
    cookies = _seed(adapter)
    result = _ask(cookies)
    assert client.post(f"/api/v1/answers/{result['answer_id']}/cancel", cookies=cookies).status_code == 200
    _run_agent(adapter, answer_id=result["answer_id"])
    answer = _get_answer(result["answer_id"], cookies)
    assert answer["status"] == "CANCELED"


# ---- TC-LG-108 幂等重投：不产生重复答案/引用 ----

def test_rerun_is_idempotent(monkeypatch) -> None:
    _enable(monkeypatch)
    adapter = FakeSearchAdapter()
    cookies = _seed(adapter)
    result = _ask(cookies)
    _run_agent(adapter, answer_id=result["answer_id"])
    answer = _get_answer(result["answer_id"], cookies)
    assert answer["status"] == "SUCCEEDED"
    cit_count = len(answer["citations"])

    _run_agent(adapter, answer_id=result["answer_id"])  # Worker 重复投递
    answer2 = _get_answer(result["answer_id"], cookies)
    assert answer2["status"] == "SUCCEEDED"
    assert len(answer2["citations"]) == cit_count


# ---- TC-LG-110 连续追问：解析上一轮实体，同时本轮重新检索 ----

def test_followup_uses_memory_entities_and_reretrieves(monkeypatch) -> None:
    _enable(monkeypatch)
    adapter = FakeSearchAdapter()
    cookies = _seed(adapter)
    result1 = _ask(cookies, "T90000 的内存是多少？")
    _run_agent(adapter, answer_id=result1["answer_id"])
    assert _get_answer(result1["answer_id"], cookies)["status"] == "SUCCEEDED"

    result2 = _ask(cookies, "那它的磁盘呢？")
    _run_agent(adapter, answer_id=result2["answer_id"])
    answer2 = _get_answer(result2["answer_id"], cookies)
    assert answer2["status"] == "SUCCEEDED"
    assert answer2["answer_type"] == "ANSWER"


# ---- TC-LG-111 长会话压缩：记忆写入 conversation_memories ----

def test_long_session_compacts_memory(monkeypatch) -> None:
    _enable(monkeypatch)
    monkeypatch.setattr(get_settings(), "conversation_compaction_trigger_ratio", 0.1)
    monkeypatch.setattr(get_settings(), "conversation_recent_token_budget", 200)
    adapter = FakeSearchAdapter()
    cookies = _seed(adapter)
    resp = client.post("/api/v1/conversations", json={"title": "长会话"}, cookies=cookies)
    assert resp.status_code == 201, resp.text
    conv_id = resp.json()["data"]["id"]
    result = None
    for i in range(8):
        result = _ask(cookies, f"T90000 的配置细节 {i} 是什么？", conv_id=conv_id)
        _run_agent(adapter, answer_id=result["answer_id"])
    with SessionLocal() as s:
        mem = s.get(ConversationMemory, uuid.UUID(conv_id))
        assert mem is not None
        assert mem.last_message_id is not None  # 水位已推进（压缩成功）


# ---- TC-LG-012 step limit：终止为明确错误 ----

def test_step_limit_terminates(monkeypatch) -> None:
    _enable(monkeypatch)
    monkeypatch.setattr(get_settings(), "agent_max_steps", 2)
    adapter = FakeSearchAdapter()
    cookies = _seed(adapter)
    result = _ask(cookies, "T90000 的内存是多少？")
    with pytest.raises(PipelineError) as exc:
        _run_agent(adapter, answer_id=result["answer_id"])
    assert exc.value.code == "AGENT_STEP_LIMIT_EXCEEDED"
    assert exc.value.retryable is False
    answer = _get_answer(result["answer_id"], cookies)
    assert answer["status"] == "FAILED"
    assert answer["error_code"] == "AGENT_STEP_LIMIT_EXCEEDED"


# ---- TC-LG-010 citation repair 最多一次 ----

def test_citation_repair_limited_to_one(monkeypatch) -> None:
    _enable(monkeypatch)
    monkeypatch.setattr(get_settings(), "feature_real_qa", True)
    adapter = FakeSearchAdapter()
    cookies = _seed(adapter)
    calls = {"generate": 0}

    def chat(messages):
        content = messages[-1]["content"]
        if "<evidence>" in content:
            calls["generate"] += 1
            if "请只引用" in content:  # 修复调用 → 输出合法引用
                return json.dumps(
                    {
                        "answer_type": "ANSWER",
                        "summary": "T90000 配置 256GB 内存。",
                        "blocks": [{"type": "paragraph", "content": "T90000 内存为 256GB。", "citation_ids": ["E1"]}],
                        "follow_up_suggestions": [],
                    }
                )
            # 首次生成输出非法引用（E99 不在证据内）
            return json.dumps(
                {
                    "answer_type": "ANSWER",
                    "summary": "T90000 配置 256GB 内存。",
                    "blocks": [{"type": "paragraph", "content": "T90000 内存为 256GB。", "citation_ids": ["E99"]}],
                    "follow_up_suggestions": [],
                }
            )
        return json.dumps(
            {
                "operation": "ANSWER",
                "standalone_query": "T90000 的内存规格",
                "detected_entities": [{"entity_type": "model", "value": "T90000"}],
                "intent_hint": None,
                "clarification_needed": False,
                "clarification_question": None,
                "reason_code": None,
            }
        )

    result = _ask(cookies, "T90000 的内存是多少？")
    _run_agent(adapter, answer_id=result["answer_id"], chat_fn=chat)
    answer = _get_answer(result["answer_id"], cookies)
    assert answer["status"] == "SUCCEEDED"
    assert calls["generate"] == 2  # 首次 + 修复一次
    assert answer["answer_type"] == "ANSWER"
