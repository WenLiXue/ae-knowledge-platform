"""会话与问答 API（DD-08 §10-14、§12 SSE）。

- conversations：新建/列表/详情/改名/归档/恢复/删除；
- messages：分页读取 + 提问（创建 UserMessage + PENDING Answer + GENERATE_ANSWER 任务）；
- answers：状态查询、SSE 事件订阅（从持久化状态重建，支持 after 游标）、取消、反馈、引用详情。

错误映射为 Problem Details 风格 {code, message}；正文/问题不进入日志。
"""

from __future__ import annotations

import json
import re
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..auth.deps import get_current_user
from ..db.models.conversation import Answer, Conversation
from ..db.models.user import User
from ..db.session import SessionLocal, get_db
from .errors import ConversationError
from .schemas import (
    AnswerOut,
    ConversationCreate,
    ConversationOut,
    ConversationUpdate,
    CreateMessageResult,
    FeedbackIn,
    MessageCreate,
    MessageOut,
)
from . import service

router = APIRouter(prefix="/api/v1", tags=["conversations"])

_TERMINAL = ("SUCCEEDED", "FAILED", "CANCELED")
_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _raise(exc: ConversationError) -> None:
    raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})


def _conversation_out(conv: Conversation) -> ConversationOut:
    return ConversationOut(
        id=conv.id,
        title=conv.title,
        status=conv.status,
        filters=conv.filters_snapshot or {},
        last_message_at=conv.last_message_at,
        created_at=conv.created_at,
    )


# ---- 会话 ----

@router.post("/conversations", status_code=status.HTTP_201_CREATED)
def create_conversation(
    data: ConversationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    try:
        conv = service.create_conversation(db, user, data.title, data.filters)
    except ConversationError as exc:
        _raise(exc)
    return {"data": _conversation_out(conv)}


@router.get("/conversations")
def list_conversations(
    include_archived: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    items = service.list_conversations(db, user, include_archived=include_archived)
    return {"data": {"items": [_conversation_out(c) for c in items]}}


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    try:
        conv = service.get_conversation(db, user, conversation_id)
    except ConversationError as exc:
        _raise(exc)
    return {"data": _conversation_out(conv)}


@router.patch("/conversations/{conversation_id}")
def patch_conversation(
    conversation_id: uuid.UUID,
    data: ConversationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    try:
        conv = service.update_conversation(db, user, conversation_id, data.title, data.filters)
    except ConversationError as exc:
        _raise(exc)
    return {"data": _conversation_out(conv)}


@router.post("/conversations/{conversation_id}/archive")
def archive_conversation(
    conversation_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    try:
        conv = service.set_conversation_status(db, user, conversation_id, "ARCHIVED")
    except ConversationError as exc:
        _raise(exc)
    return {"data": _conversation_out(conv)}


@router.post("/conversations/{conversation_id}/restore")
def restore_conversation(
    conversation_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    try:
        conv = service.set_conversation_status(db, user, conversation_id, "ACTIVE")
    except ConversationError as exc:
        _raise(exc)
    return {"data": _conversation_out(conv)}


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    try:
        service.set_conversation_status(db, user, conversation_id, "DELETED")
    except ConversationError as exc:
        _raise(exc)


# ---- 消息 ----

@router.get("/conversations/{conversation_id}/messages")
def list_messages(
    conversation_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    try:
        items: list[MessageOut] = service.list_messages(db, user, conversation_id)
    except ConversationError as exc:
        _raise(exc)
    return {"data": {"items": [m.model_dump(mode="json") for m in items]}}


@router.post("/conversations/{conversation_id}/messages", status_code=status.HTTP_202_ACCEPTED)
def create_message(
    conversation_id: uuid.UUID,
    data: MessageCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    try:
        result: CreateMessageResult = service.create_question(
            db, user, conversation_id, data.content, data.filters
        )
    except ConversationError as exc:
        _raise(exc)
    return {"data": result.model_dump(mode="json")}


# ---- 回答 ----

@router.get("/answers/{answer_id}")
def get_answer(
    answer_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    try:
        answer = service.get_answer(db, user, answer_id)
    except ConversationError as exc:
        _raise(exc)
    return {"data": service.build_answer_out(db, answer).model_dump(mode="json")}


@router.get("/answers/{answer_id}/events")
def answer_events(
    answer_id: uuid.UUID,
    after: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """SSE 订阅回答进度与最终结果（DD-08 §12）。

    从持久化状态重建事件（不依赖 Worker 内存流）；`after` 传上次收到的 event id 可恢复。
    连接建立先发 snapshot；终结后发 blocks/citations/done。心跳 15s，最长时间约 600s。
    """
    try:
        service.get_answer(db, user, answer_id)
    except ConversationError as exc:
        _raise(exc)

    def stream():
        after_no = _cursor_seq(after)
        last_signal: tuple[str, str | None] | None = None
        last_heartbeat = time.monotonic()
        deadline = time.monotonic() + 600
        with SessionLocal() as session:
            answer = session.get(Answer, answer_id)
            if answer is None:
                return
            if answer.status in _TERMINAL:
                # 终结回答按确定性序号重建事件；已收 done 的客户端不再重发（AC-QA-002）
                finals = list(_final_events(session, answer))
                last_seq = 2 + len(finals)
                if after_no >= last_seq:
                    return
                if after_no < 1:
                    payload = service.build_answer_out(session, answer).model_dump(mode="json")
                    yield _sse_event("e1:snapshot", "answer.snapshot", payload)
                if after_no < 2:
                    yield _status_event(answer)
                for seq, name, data in finals:
                    if seq > after_no:
                        yield _sse_event(f"e{seq}:{name}:{_event_suffix(name, data)}", name, data)
                return
            # 进行中：发当前快照 + 状态，轮询状态变化（进度事件为瞬时态，断线后不逐条补发）
            payload = service.build_answer_out(session, answer).model_dump(mode="json")
            yield _sse_event("e1:snapshot", "answer.snapshot", payload)
            last_signal = (answer.status, answer.progress_stage)
            yield _status_event(answer)
        while time.monotonic() < deadline:
            with SessionLocal() as session:
                answer = session.get(Answer, answer_id)
                if answer is None:
                    break
                signal = (answer.status, answer.progress_stage)
                if signal != last_signal:
                    last_signal = signal
                    yield _status_event(answer)
                if answer.status in _TERMINAL:
                    for seq, name, data in _final_events(session, answer):
                        yield _sse_event(f"e{seq}:{name}:{_event_suffix(name, data)}", name, data)
                    return
            now = time.monotonic()
            if now - last_heartbeat >= 15:
                last_heartbeat = now
                yield _sse_event(f"heartbeat:{int(now)}", "heartbeat", {})
            time.sleep(1.0)

    return StreamingResponse(stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/answers/{answer_id}/cancel")
def cancel_answer(
    answer_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    try:
        answer = service.request_cancel(db, user, answer_id)
    except ConversationError as exc:
        _raise(exc)
    return {"data": service.build_answer_out(db, answer).model_dump(mode="json")}


@router.post("/answers/{answer_id}/retry")
def retry_answer(
    answer_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    try:
        answer = service.retry_answer(db, user, answer_id)
    except ConversationError as exc:
        _raise(exc)
    return {"data": {
        "message_id": str(answer.message_id),
        "answer_id": str(answer.id),
        "status": answer.status,
        "events_url": f"/api/v1/answers/{answer.id}/events",
    }}


@router.put("/answers/{answer_id}/feedback")
def put_feedback(
    answer_id: uuid.UUID,
    data: FeedbackIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    try:
        service.upsert_feedback(db, user, answer_id, data)
    except ConversationError as exc:
        _raise(exc)
    return {"data": {"answer_id": str(answer_id), "status": "SAVED"}}


@router.get("/answers/{answer_id}/citations/{citation_no}")
def get_citation(
    answer_id: uuid.UUID,
    citation_no: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    try:
        detail = service.citation_detail(db, user, answer_id, citation_no)
    except ConversationError as exc:
        _raise(exc)
    return {"data": detail.model_dump(mode="json")}


# ---- SSE 事件构造 ----

def _sse_event(event_id: str, event_name: str, data: dict) -> str:
    return f"id: {event_id}\nevent: {event_name}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _cursor_seq(after: str | None) -> int:
    """从事件 id 提取序号（e{seq}:...）。非数字形式返回 0。"""
    match = re.search(r"e(\d+):", after or "")
    return int(match.group(1)) if match else 0


def _event_suffix(name: str, data: dict) -> str:
    if name == "answer.block":
        return str(data.get("block_id", "b"))
    if name == "answer.citation":
        return str(data.get("citation_no", "0"))
    return "done"


def _status_event(answer: Answer) -> str:
    return _sse_event(
        f"e2:status:{answer.updated_at.isoformat()}:{answer.status}",
        "answer.status",
        {
            "answer_id": str(answer.id),
            "status": answer.status,
            "progress_stage": answer.progress_stage,
        },
    )


def _final_events(session: Session, answer: Answer):
    """终结后按序输出：blocks → citations → done。序号从 3 起、确定性（可续传）。"""
    answer_out = service.build_answer_out(session, answer)
    seq = 2
    for block in answer_out.blocks:
        seq += 1
        yield seq, "answer.block", block.model_dump(mode="json")
    for citation in answer_out.citations:
        seq += 1
        yield seq, "answer.citation", citation.model_dump(mode="json")
    seq += 1
    yield seq, "answer.done", {
        "answer_id": str(answer.id),
        "status": answer.status,
        "answer_type": answer.answer_type,
    }
