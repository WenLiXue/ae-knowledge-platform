"""飞书文档提交/来源查询/重试的数据库集成测试。

覆盖：正常提交落库、重复提交不重复建源、单批内重复 409、
批量部分成功、来源列表与详情、发现接口反映已提交状态、
失败来源可重试（创建新任务并关联旧任务）、不可重试 409、来源 404。
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.session import SessionLocal
from app.main import app


client = TestClient(app)

TOKEN_HW = "wiki-hardware-spec"


def _submit(token: str, resource_type: str = "wiki", client_item_id: str = "row-1") -> dict:
    response = client.post(
        "/api/v1/feishu/documents/submit",
        json={
            "items": [
                {
                    "client_item_id": client_item_id,
                    "resource_token": token,
                    "resource_type": resource_type,
                }
            ]
        },
    )
    assert response.status_code == 202, response.text
    return response.json()["data"]["items"][0]


def _count_rows(table: str) -> int:
    with SessionLocal() as db:
        return db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def _mark_source_failed(source_id: str) -> None:
    """模拟首版处理失败：任务、版本、来源同时置为 FAILED。"""
    with SessionLocal() as db:
        db.execute(
            text(
                "UPDATE tasking.processing_tasks SET status='FAILED', "
                "last_error_code='SIMULATED', last_error_summary='simulated failure' "
                "WHERE source_id=:sid"
            ),
            {"sid": source_id},
        )
        db.execute(
            text(
                "UPDATE knowledge.document_versions SET status='FAILED' "
                "WHERE source_id=:sid"
            ),
            {"sid": source_id},
        )
        db.execute(
            text("UPDATE knowledge.knowledge_sources SET status='FAILED' WHERE id=:sid"),
            {"sid": source_id},
        )
        db.commit()


def test_duplicate_submission_returns_existing() -> None:
    first = _submit(TOKEN_HW)
    second = _submit(TOKEN_HW)

    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert second["source_id"] == first["source_id"]
    # 重复提交不重复建源、不重复建任务
    assert _count_rows("knowledge.knowledge_sources") == 1
    assert _count_rows("tasking.processing_tasks") == 1


def test_duplicate_token_in_single_batch_conflict() -> None:
    response = client.post(
        "/api/v1/feishu/documents/submit",
        json={
            "items": [
                {"client_item_id": "a", "resource_token": TOKEN_HW, "resource_type": "wiki"},
                {"client_item_id": "b", "resource_token": TOKEN_HW, "resource_type": "wiki"},
            ]
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "DUPLICATE_SUBMISSION"
    assert _count_rows("knowledge.knowledge_sources") == 0


def test_batch_partial_success() -> None:
    _submit(TOKEN_HW)
    response = client.post(
        "/api/v1/feishu/documents/submit",
        json={
            "items": [
                {"client_item_id": "new", "resource_token": "wiki-seg-cases", "resource_type": "wiki"},
                {"client_item_id": "dup", "resource_token": TOKEN_HW, "resource_type": "wiki"},
            ]
        },
    )

    assert response.status_code == 202
    items = response.json()["data"]["items"]
    by_id = {item["client_item_id"]: item for item in items}
    assert by_id["new"]["duplicate"] is False
    assert by_id["new"]["status"] == "PROCESSING"
    assert by_id["dup"]["duplicate"] is True
    assert by_id["new"]["source_id"] != by_id["dup"]["source_id"]
    assert _count_rows("knowledge.knowledge_sources") == 2


def test_knowledge_sources_list_and_detail() -> None:
    submitted = _submit(TOKEN_HW)
    source_id = submitted["source_id"]

    listing = client.get("/api/v1/knowledge-sources")
    assert listing.status_code == 200
    items = listing.json()["data"]["items"]
    assert len(items) == 1
    item = items[0]
    assert item["source_id"] == source_id
    assert item["resource_token"] == TOKEN_HW
    assert item["status"] == "PROCESSING"
    assert item["version_status"] == "PROCESSING"
    assert item["task_status"] == "PENDING"

    detail = client.get(f"/api/v1/knowledge-sources/{source_id}")
    assert detail.status_code == 200
    body = detail.json()["data"]
    assert body["source_id"] == source_id
    assert body["display_name"] == "AE 产品硬件规格"
    assert body["processing_stage"] == "FETCHING"


def test_documents_reflect_submitted_from_db() -> None:
    # 提交前：未标记
    before = client.get("/api/v1/feishu/documents").json()["data"]["items"]
    hw_before = next(i for i in before if i["resource_token"] == TOKEN_HW)
    assert hw_before["submitted"] is False

    submitted = _submit(TOKEN_HW)
    after = client.get("/api/v1/feishu/documents").json()["data"]["items"]
    hw_after = next(i for i in after if i["resource_token"] == TOKEN_HW)
    assert hw_after["submitted"] is True
    assert hw_after["source_id"] == submitted["source_id"]


def test_retry_failed_source_creates_new_task() -> None:
    submitted = _submit(TOKEN_HW)
    source_id = submitted["source_id"]
    old_task_id = submitted["task_id"]
    _mark_source_failed(source_id)

    response = client.post(f"/api/v1/knowledge-sources/{source_id}/retry")
    assert response.status_code == 202
    body = response.json()["data"]
    assert body["status"] == "PROCESSING"
    assert body["retry_created"] is True
    assert body["task_status"] == "PENDING"

    # 新任务关联旧任务；来源回到 PROCESSING
    with SessionLocal() as db:
        row = db.execute(
            text("SELECT parent_task_id FROM tasking.processing_tasks WHERE id=:tid"),
            {"tid": body["task_id"]},
        ).one_or_none()
        src_status = db.execute(
            text("SELECT status FROM knowledge.knowledge_sources WHERE id=:sid"),
            {"sid": source_id},
        ).scalar_one()
    assert row is not None
    assert str(row[0]) == old_task_id
    assert src_status == "PROCESSING"


def test_retry_is_idempotent() -> None:
    submitted = _submit(TOKEN_HW)
    source_id = submitted["source_id"]
    _mark_source_failed(source_id)

    first = client.post(f"/api/v1/knowledge-sources/{source_id}/retry")
    second = client.post(f"/api/v1/knowledge-sources/{source_id}/retry")

    assert first.status_code == 202
    # 重试成功后来源为 PROCESSING，再次重试不再创建第二个任务
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "SOURCE_NOT_RETRYABLE"
    assert _count_rows("tasking.processing_tasks") == 2  # 原任务 + 重试任务


def test_retry_not_allowed_for_processing_source() -> None:
    submitted = _submit(TOKEN_HW)
    response = client.post(f"/api/v1/knowledge-sources/{submitted['source_id']}/retry")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SOURCE_NOT_RETRYABLE"


def test_source_not_found() -> None:
    missing = str(uuid.uuid4())

    detail = client.get(f"/api/v1/knowledge-sources/{missing}")
    assert detail.status_code == 404
    assert detail.json()["detail"]["code"] == "SOURCE_NOT_FOUND"

    retry = client.post(f"/api/v1/knowledge-sources/{missing}/retry")
    assert retry.status_code == 404
