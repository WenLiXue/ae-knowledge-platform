"""Agent 运行时恢复测试（DD-21 TC-LG-107 检索后崩溃恢复、checkpoint 语义）。"""

from __future__ import annotations

import datetime
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.agent.context import build_context
from app.agent.runtime import create_checkpointer, run_agent
from app.agent.state import build_initial_state
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.db.models.conversation import AgentRun, Answer
from app.main import app
from app.search.fake import FakeSearchAdapter

from _seed_retrieval import (
    add_document,
    fake_retrieval_service,
    make_user,
    seed_catalog,
    user_cookies,
)


class _ProcessKill(BaseException):
    """模拟进程崩溃（BaseException 不会被 except Exception 捕获）。"""


def _prepare_answer(adapter: FakeSearchAdapter) -> str:
    """建会话+问题+answer；索引 4 个 chunk 使证据 SUFFICIENT（避免改写循环干扰计数）。"""
    client = TestClient(app)
    with SessionLocal() as s:
        cat = seed_catalog(s)
        add_document(
            s, adapter, display_name="AE 硬件规格", doc_type=cat["spec"],
            product=cat["product"], product_version=cat["product_version"],
            chunks=[
                "T90000 CPU AMD EPYC 7H12 主频 2.6GHz",
                "T90000 内存 256GB DDR4 ECC",
                "T90000 磁盘 16TB NVMe SSD",
                "T90000 网络 2x10GbE 板载",
            ],
        )
        s.commit()
        user = make_user(s, display_name="恢复用户")
        cookies = user_cookies(s, user)
        s.commit()
    resp = client.post("/api/v1/conversations", json={"title": "恢复"}, cookies=cookies)
    conv = resp.json()["data"]
    resp = client.post(
        f"/api/v1/conversations/{conv['id']}/messages",
        json={"content": "T90000 的内存是多少？"},
        cookies=cookies,
    )
    return resp.json()["data"]["answer_id"]


def _initial(answer_id, conversation_id, user_id):
    return build_initial_state(
        answer_id=answer_id,
        conversation_id=conversation_id,
        user_id=user_id,
        run_id=str(uuid.uuid4()),
        graph_version=get_settings().agent_graph_version,
    )


def test_resume_after_crash_does_not_repeat_completed_nodes(monkeypatch) -> None:
    """检索完成后进程崩溃 → 恢复后复用已完成节点，检索重跑一次并完成。"""
    monkeypatch.setattr(get_settings(), "agent_graph_enabled", True)
    monkeypatch.setattr(get_settings(), "feature_real_qa", False)
    adapter = FakeSearchAdapter()
    answer_id = _prepare_answer(adapter)

    with SessionLocal() as s:
        answer = s.get(Answer, uuid.UUID(answer_id))
        conversation_id = str(answer.conversation_id)
        user_id = str(answer.user_id)

    initial = _initial(answer_id, conversation_id, user_id)
    cp = create_checkpointer(settings=get_settings())
    calls = {"retrieve": 0}

    def svc_factory():
        svc = fake_retrieval_service(adapter)
        orig = svc.retrieve

        def counted(db, question, filters=None, **kwargs):
            calls["retrieve"] += 1
            if calls["retrieve"] == 1:
                raise _ProcessKill("模拟检索阶段进程崩溃")
            return orig(db, question, filters=filters, **kwargs)

        svc.retrieve = counted
        return svc

    def make_ctx():
        return build_context(
            settings=get_settings(),
            retrieval_service_factory=svc_factory,
            clock=lambda: datetime.datetime.now(datetime.timezone.utc),
        )

    with pytest.raises(_ProcessKill):
        run_agent(initial, context=make_ctx(), checkpointer=cp, settings=get_settings())

    # 第二次 attempt：同 answer_id/thread_id → 从 checkpoint 恢复
    result = run_agent(initial, context=make_ctx(), checkpointer=cp, settings=get_settings())
    assert result.get("final_status") == "SUCCEEDED"
    # 崩溃那次（1 次）+ 恢复后重跑（≥1 次）；检索可能再触发一次合法改写
    assert calls["retrieve"] >= 2
    load_states = [t for t in (result.get("node_trace") or []) if t.get("node") == "load_state"]
    assert len(load_states) == 1  # 恢复后不重复执行已完成的 load_state
    cp.conn.close()


def test_completed_run_resume_is_idempotent(monkeypatch) -> None:
    """持久化后 Worker 重试：checkpoint 终态直接返回，不重跑节点。"""
    monkeypatch.setattr(get_settings(), "agent_graph_enabled", True)
    monkeypatch.setattr(get_settings(), "feature_real_qa", False)
    adapter = FakeSearchAdapter()
    answer_id = _prepare_answer(adapter)

    with SessionLocal() as s:
        answer = s.get(Answer, uuid.UUID(answer_id))
        conversation_id = str(answer.conversation_id)
        user_id = str(answer.user_id)

    initial = _initial(answer_id, conversation_id, user_id)
    cp = create_checkpointer(settings=get_settings())
    ctx = build_context(
        settings=get_settings(),
        retrieval_service_factory=lambda: fake_retrieval_service(adapter),
        clock=lambda: datetime.datetime.now(datetime.timezone.utc),
    )

    result1 = run_agent(initial, context=ctx, checkpointer=cp, settings=get_settings())
    assert result1.get("final_status") == "SUCCEEDED"
    with SessionLocal() as s:
        run = s.execute(
            select(AgentRun).where(AgentRun.answer_id == uuid.UUID(answer_id))
        ).scalars().first()
        assert run is not None and run.status == "SUCCEEDED"

    def _cit_count():
        with SessionLocal() as s:
            return s.execute(
                text("SELECT count(*) FROM conversation.answer_citations WHERE answer_id = :a"),
                {"a": uuid.UUID(answer_id)},
            ).scalar_one()

    before = _cit_count()
    assert before > 0  # 本轮确有引用
    result2 = run_agent(initial, context=ctx, checkpointer=cp, settings=get_settings())
    assert result2.get("final_status") == "SUCCEEDED"
    assert _cit_count() == before  # 重投不产生重复引用
    cp.conn.close()


def test_checkpoint_cleanup_respects_retention(monkeypatch) -> None:
    """按 agent_runs 终态保留期清理 checkpoint，不删除业务数据。"""
    from datetime import datetime, timedelta, timezone

    from app.agent.runtime import cleanup_checkpoints
    from app.db.models.conversation import AgentRun

    monkeypatch.setattr(get_settings(), "agent_graph_enabled", True)
    monkeypatch.setattr(get_settings(), "feature_real_qa", False)
    adapter = FakeSearchAdapter()
    answer_id = _prepare_answer(adapter)

    with SessionLocal() as s:
        answer = s.get(Answer, uuid.UUID(answer_id))
        conversation_id = str(answer.conversation_id)
        user_id = str(answer.user_id)

    initial = _initial(answer_id, conversation_id, user_id)
    cp = create_checkpointer(settings=get_settings())
    ctx = build_context(
        settings=get_settings(),
        retrieval_service_factory=lambda: fake_retrieval_service(adapter),
        clock=lambda: datetime.now(timezone.utc),
    )
    run_agent(initial, context=ctx, checkpointer=cp, settings=get_settings())
    assert cp.get_tuple({"configurable": {"thread_id": answer_id}}) is not None

    # 把 AgentRun 改成很久以前完成 → 过期清理
    with SessionLocal() as s:
        run = s.execute(
            select(AgentRun).where(AgentRun.answer_id == uuid.UUID(answer_id))
        ).scalars().first()
        run.completed_at = datetime.now(timezone.utc) - timedelta(days=99)
        s.commit()

    removed = cleanup_checkpoints(
        cp,
        success_retention_days=0,
        failed_retention_days=0,
    )
    assert removed >= 1
    assert cp.get_tuple({"configurable": {"thread_id": answer_id}}) is None
    # 业务数据仍在
    with SessionLocal() as s:
        assert s.get(Answer, uuid.UUID(answer_id)) is not None
        assert s.execute(
            text("SELECT count(*) FROM conversation.answer_citations WHERE answer_id = :a"),
            {"a": uuid.UUID(answer_id)},
        ).scalar_one() > 0
    cp.conn.close()
