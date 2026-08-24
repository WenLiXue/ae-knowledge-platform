import uuid

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ae-knowledge-platform-api",
    }


def test_submit_feishu_documents() -> None:
    response = client.post(
        "/api/v1/feishu/documents/submit",
        json={
            "items": [
                {
                    "client_item_id": "row-1",
                    "resource_token": "wiki-hardware-spec",
                    "resource_type": "wiki",
                }
            ]
        },
    )

    assert response.status_code == 202
    item = response.json()["data"]["items"][0]
    assert item["status"] == "PROCESSING"
    assert item["duplicate"] is False
    # 来源主键为数据库 UUID，不再是内存演示的 src_ 前缀
    assert uuid.UUID(item["source_id"])
    assert item["version_id"]
    assert item["task_id"]
