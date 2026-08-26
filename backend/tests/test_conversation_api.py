"""会话与问答 API 测试（DD-08 §10-14、DD-10，Phase 6）。

覆盖：会话 CRUD/归档/删除、提问事务（409 ANSWER_ALREADY_IN_PROGRESS）、
答案完成（worker → SUCCEEDED + 引用）、反馈幂等、取消、所有权、SSE 事件重建。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app

from _seed_retrieval import (
    add_document,
    make_user,
    run_answer_task,
    seed_catalog,
    user_cookies,
)
from app.search.fake import FakeSearchAdapter

client = TestClient(app)


def _seed_kb():
    with SessionLocal() as s:
        cat = seed_catalog(s)
        adapter = FakeSearchAdapter()
        add_document(
            s, adapter, display_name="AE 硬件规格", doc_type=cat["spec"],
            product=cat["product"], product_version=cat["product_version"],
            chunks=["E3800 防病毒吞吐量 3.5G 物理吞吐量 15G 内存 64G DDR4",
                    "T90000 CPU AMD EPYC 7H12 内存 256GB 磁盘 16TB"],
        )
        add_document(
            s, adapter, display_name="V7.0 产品白皮书", doc_type=cat["wp"],
            product=cat["product"], product_version=cat["product_version"],
            chunks=["信舷防毒墙是下一代内容安全网关 支持网桥模式"],
        )
        s.commit()
        user = make_user(s, display_name="提问用户")
        cookies = user_cookies(s, user)
        other = make_user(s, display_name="其他用户")
        other_cookies = user_cookies(s, other)
        s.commit()
    return adapter, cookies, other_cookies


def _create_conversation(cookies, title="新会话") -> dict:
    resp = client.post("/api/v1/conversations", json={"title": title}, cookies=cookies)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def _ask(cookies, conversation_id, content) -> dict:
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": content},
        cookies=cookies,
    )
    assert resp.status_code == 202, resp.text
    return resp.json()["data"]


def test_conversation_crud_and_ownership() -> None:
    adapter, cookies, other_cookies = _seed_kb()

    conv = _create_conversation(cookies, title="T90000 咨询")
    assert conv["title"] == "T90000 咨询"
    assert conv["status"] == "ACTIVE"

    listed = client.get("/api/v1/conversations", cookies=cookies).json()["data"]["items"]
    assert any(c["id"] == conv["id"] for c in listed)

    got = client.get(f"/api/v1/conversations/{conv['id']}", cookies=cookies).json()["data"]
    assert got["id"] == conv["id"]

    # 其他用户不可见（404 防枚举）
    resp = client.get(f"/api/v1/conversations/{conv['id']}", cookies=other_cookies)
    assert resp.status_code == 404


def test_create_question_creates_answer_and_task() -> None:
    from sqlalchemy import select, text

    from app.db.models.task import ProcessingTask

    adapter, cookies, _ = _seed_kb()
    conv = _create_conversation(cookies)
    result = _ask(cookies, conv["id"], "E3800 的防病毒吞吐量和内存是多少？")

    assert result["status"] == "PENDING"
    assert result["message_id"] and result["answer_id"]
    assert result["events_url"] == f"/api/v1/answers/{result['answer_id']}/events"

    with SessionLocal() as s:
        task = s.execute(
            select(ProcessingTask).where(ProcessingTask.task_type == "GENERATE_ANSWER")
        ).scalars().first()
        assert task is not None
        assert task.payload["answer_id"] == result["answer_id"]
        # 标题自动取问题前 20 字
        title = s.execute(
            text("SELECT title FROM conversation.conversations WHERE id=:cid"),
            {"cid": conv["id"]},
        ).scalar_one()
        assert title == "E3800 的防病毒吞吐量和内存是多少？"


def test_concurrent_question_returns_409() -> None:
    adapter, cookies, _ = _seed_kb()
    conv = _create_conversation(cookies)
    _ask(cookies, conv["id"], "E3800 的吞吐量？")

    resp = client.post(
        f"/api/v1/conversations/{conv['id']}/messages",
        json={"content": "T90000 的内存？"},
        cookies=cookies,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "ANSWER_ALREADY_IN_PROGRESS"


def test_archive_blocks_question_and_restore_allows() -> None:
    adapter, cookies, _ = _seed_kb()
    conv = _create_conversation(cookies)

    assert client.post(f"/api/v1/conversations/{conv['id']}/archive", cookies=cookies).status_code == 200
    resp = client.post(
        f"/api/v1/conversations/{conv['id']}/messages", json={"content": "问题"}, cookies=cookies
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "CONVERSATION_NOT_ACTIVE"

    assert client.post(f"/api/v1/conversations/{conv['id']}/restore", cookies=cookies).status_code == 200
    assert _ask(cookies, conv["id"], "恢复后提问").get("answer_id")


def test_delete_hides_conversation() -> None:
    adapter, cookies, _ = _seed_kb()
    conv = _create_conversation(cookies)

    assert client.delete(f"/api/v1/conversations/{conv['id']}", cookies=cookies).status_code == 204
    assert client.get(f"/api/v1/conversations/{conv['id']}", cookies=cookies).status_code == 404
    listed = client.get("/api/v1/conversations", cookies=cookies).json()["data"]["items"]
    assert all(c["id"] != conv["id"] for c in listed)


def test_answer_completes_with_evidence_and_citations() -> None:
    from app.db.models.conversation import Answer, AnswerCitation
    from app.db.models.conversation import RetrievalRun
    from sqlalchemy import select

    adapter, cookies, _ = _seed_kb()
    conv = _create_conversation(cookies)
    result = _ask(cookies, conv["id"], "E3800 的防病毒吞吐量和内存是多少？")

    run_answer_task(adapter, answer_id=result["answer_id"])

    answer_resp = client.get(f"/api/v1/answers/{result['answer_id']}", cookies=cookies)
    assert answer_resp.status_code == 200
    answer = answer_resp.json()["data"]
    assert answer["status"] == "SUCCEEDED"
    assert answer["answer_type"] == "ANSWER"
    assert answer["summary"]
    assert len(answer["blocks"]) >= 1
    assert all(block["citation_nos"] for block in answer["blocks"])
    assert len(answer["citations"]) >= 1
    citation = answer["citations"][0]
    assert citation["document_title"] == "AE 硬件规格"
    assert citation["availability"] == "AVAILABLE"
    assert citation["heading_path"]

    # 消息流：用户 + 助手（含 answer）
    messages = client.get(f"/api/v1/conversations/{conv['id']}/messages", cookies=cookies).json()["data"]["items"]
    roles = [m["role"] for m in messages]
    assert roles == ["user", "assistant"]
    assert messages[1]["answer"]["id"] == result["answer_id"]

    # 持久化断言：answer + citations + retrieval_run 关联
    import uuid

    with SessionLocal() as s:
        answer_row = s.get(Answer, uuid.UUID(result["answer_id"]))
        assert answer_row is not None
        assert answer_row.status == "SUCCEEDED"
        assert answer_row.retrieval_run_id is not None
        assert s.get(RetrievalRun, answer_row.retrieval_run_id) is not None
        citations = list(s.execute(
            select(AnswerCitation).where(AnswerCitation.answer_id == answer_row.id)
        ).scalars())
        assert len(citations) == len(answer["citations"])


def test_feedback_idempotent_and_only_on_succeeded() -> None:
    adapter, cookies, _ = _seed_kb()
    conv = _create_conversation(cookies)

    # PENDING 阶段反馈被拒
    result = _ask(cookies, conv["id"], "E3800 的吞吐量？")
    resp = client.put(
        f"/api/v1/answers/{result['answer_id']}/feedback",
        json={"rating": "HELPFUL"},
        cookies=cookies,
    )
    assert resp.status_code == 409

    run_answer_task(adapter, answer_id=result["answer_id"])
    data = {"rating": "NOT_HELPFUL", "reason_codes": ["MISSING_KEY_POINT"], "comment": "缺细节"}
    resp1 = client.put(
        f"/api/v1/answers/{result['answer_id']}/feedback", json=data, cookies=cookies
    )
    assert resp1.status_code == 200
    # 重复提交 → 幂等更新（仍 200）
    resp2 = client.put(
        f"/api/v1/answers/{result['answer_id']}/feedback",
        json={"rating": "HELPFUL"},
        cookies=cookies,
    )
    assert resp2.status_code == 200

    from sqlalchemy import text

    with SessionLocal() as s:
        count = s.execute(
            text("SELECT count(*) FROM conversation.answer_feedback WHERE answer_id=:aid"),
            {"aid": result["answer_id"]},
        ).scalar_one()
        rating = s.execute(
            text("SELECT rating FROM conversation.answer_feedback WHERE answer_id=:aid"),
            {"aid": result["answer_id"]},
        ).scalar_one()
    assert count == 1
    assert rating == "HELPFUL"


def test_cancel_marks_cancel_requested_then_worker_cancels() -> None:
    from sqlalchemy import text

    adapter, cookies, _ = _seed_kb()
    conv = _create_conversation(cookies)
    result = _ask(cookies, conv["id"], "E3800 的吞吐量？")

    resp = client.post(f"/api/v1/answers/{result['answer_id']}/cancel", cookies=cookies)
    assert resp.status_code == 200
    with SessionLocal() as s:
        requested = s.execute(
            text("SELECT cancel_requested FROM conversation.answers WHERE id=:aid"),
            {"aid": result["answer_id"]},
        ).scalar_one()
    assert requested is True

    run_answer_task(adapter, answer_id=result["answer_id"])
    answer = client.get(f"/api/v1/answers/{result['answer_id']}", cookies=cookies).json()["data"]
    assert answer["status"] == "CANCELED"
