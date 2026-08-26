"""回答 SSE 事件测试（DD-08 §12，Phase 6）。

覆盖：SUCCEEDED 回答的 snapshot/status/block/citation/done 事件重建；
`after` 游标续传（跳过已收事件）；心跳与终结事件。
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.search.fake import FakeSearchAdapter

from _seed_retrieval import (
    add_document,
    make_user,
    run_answer_task,
    seed_catalog,
    user_cookies,
)

client = TestClient(app)


def _setup() -> tuple[str, str, str, dict]:
    """返回 (adapter, answer_id, conversation_id, cookies)。"""
    adapter = FakeSearchAdapter()
    with SessionLocal() as s:
        cat = seed_catalog(s)
        add_document(
            s, adapter, display_name="AE 硬件规格", doc_type=cat["spec"],
            product=cat["product"], product_version=cat["product_version"],
            chunks=["E3800 防病毒吞吐量 3.5G 内存 64G DDR4"],
        )
        s.commit()
        user = make_user(s, display_name="SSE 用户")
        cookies = user_cookies(s, user)
        s.commit()
    resp = client.post("/api/v1/conversations", json={}, cookies=cookies)
    conv = resp.json()["data"]
    resp = client.post(
        f"/api/v1/conversations/{conv['id']}/messages",
        json={"content": "E3800 的吞吐量和内存是多少？"},
        cookies=cookies,
    )
    result = resp.json()["data"]
    run_answer_task(adapter, answer_id=result["answer_id"])
    return adapter, result["answer_id"], conv["id"], cookies


def _parse_events(body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    event_name = None
    data_lines: list[str] = []
    for line in body.splitlines():
        if line.startswith("event:"):
            event_name = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:"):].strip())
        elif line == "" and event_name:
            events.append((event_name, json.loads("\n".join(data_lines))))
            event_name = None
            data_lines = []
    if event_name:
        events.append((event_name, json.loads("\n".join(data_lines))))
    return events


def test_sse_succeeded_answer_reconstructs_final_events() -> None:
    _, answer_id, _, cookies = _setup()
    resp = client.get(f"/api/v1/answers/{answer_id}/events", cookies=cookies)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _parse_events(resp.text)
    names = [name for name, _ in events]
    assert names[0] == "answer.snapshot"
    assert "answer.status" in names
    assert "answer.block" in names
    assert "answer.citation" in names
    assert names[-1] == "answer.done"

    done = events[-1][1]
    assert done["status"] == "SUCCEEDED"
    assert done["answer_id"] == answer_id

    block = next(data for name, data in events if name == "answer.block")
    assert block["type"] == "paragraph"
    assert block["citation_nos"]


def test_sse_resume_after_snapshot_skips_snapshot_but_keeps_final() -> None:
    _, answer_id, _, cookies = _setup()
    resp = client.get(
        f"/api/v1/answers/{answer_id}/events", params={"after": "e1:snapshot"}, cookies=cookies
    )
    events = _parse_events(resp.text)
    names = [name for name, _ in events]
    assert "answer.snapshot" not in names
    assert "answer.status" in names
    assert "answer.done" in names

    # 已收首个 block 后重连：不再发 snapshot/block，只补 citation 与 done
    resp2 = client.get(
        f"/api/v1/answers/{answer_id}/events", params={"after": "e3:block:b1"}, cookies=cookies
    )
    events2 = _parse_events(resp2.text)
    names2 = [name for name, _ in events2]
    assert "answer.snapshot" not in names2
    assert "answer.block" not in names2
    assert names2[-1] == "answer.done"


def test_sse_no_events_after_done() -> None:
    _, answer_id, _, cookies = _setup()
    # done 序号 = 2（snapshot/status）+ blocks + citations + 1；用一个远超实际序号的值确保覆盖
    resp = client.get(
        f"/api/v1/answers/{answer_id}/events", params={"after": "e999:done"}, cookies=cookies
    )
    events = _parse_events(resp.text)
    assert events == []
