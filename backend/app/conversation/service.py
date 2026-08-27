"""会话与问答领域服务（DD-08 §10-14、DD-10）。

- 会话 CRUD / 归档 / 恢复 / 逻辑删除；
- 提问事务（DD-10 §3）：锁会话 → 校验 ACTIVE 与无未终结回答 → 建 UserMessage +
  PENDING Answer + GENERATE_ANSWER 任务（原子提交）；
- 消息/回答读取：assistant 消息由 Answer 合成，不物理覆盖历史；
- 取消：设置 cancel_requested，Worker 在阶段边界转 CANCELED；
- 反馈：(answer_id, user_id) 唯一、幂等更新，仅 SUCCEEDED 可反馈。
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models.conversation import (
    Answer,
    AnswerCitation,
    AnswerFeedback,
    Conversation,
    Message,
)
from ..db.models.knowledge import KnowledgeSource
from ..db.models.task import ProcessingTask
from ..db.models.user import User
from ..core.config import get_settings
from ..retrieval.filters import validate_filters as validate_retrieval_filters
from ..retrieval.schemas import RetrievalFilters
from .errors import ConversationError
from .schemas import (
    AnswerBlock,
    AnswerCitationOut,
    AnswerOut,
    CitationLocationOut,
    CitationDetailOut,
    CreateMessageResult,
    FeedbackIn,
    MessageOut,
    QueryFilters,
)

_OPEN_STATUSES = ("PENDING", "RETRIEVING", "STREAMING")
_MAX_QUESTION_CHARS = 4000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def recover_stale_answers(db: Session, conversation_id=None) -> int:
    """把超过租期仍未推进的回答收敛为 FAILED，避免永久占用会话。"""
    cutoff = _now() - timedelta(seconds=get_settings().answer_stale_timeout_seconds)
    stmt = select(Answer).where(
        Answer.status.in_(_OPEN_STATUSES),
        Answer.updated_at < cutoff,
    )
    if conversation_id is not None:
        stmt = stmt.where(Answer.conversation_id == conversation_id)
    stale = list(db.execute(stmt).scalars())
    for answer in stale:
        answer.status = "FAILED"
        answer.progress_stage = None
        answer.error_code = "ANSWER_STALE"
        answer.error_summary = "回答处理超时，已结束本次生成；可以重新提问。"
        answer.completed_at = _now()
    if stale:
        db.flush()
    return len(stale)


# ---- 过滤器快照 ----

def filters_to_snapshot(filters: QueryFilters | None) -> dict:
    if filters is None:
        return {"product_id": None, "product_version_id": None, "document_type_id": None}
    return {
        "product_id": str(filters.product_id) if filters.product_id else None,
        "product_version_id": str(filters.product_version_id) if filters.product_version_id else None,
        "document_type_id": str(filters.document_type_id) if filters.document_type_id else None,
    }


def filters_from_snapshot(snapshot: dict | None) -> QueryFilters:
    snapshot = snapshot or {}
    return QueryFilters(
        product_id=_uuid_or_none(snapshot.get("product_id")),
        product_version_id=_uuid_or_none(snapshot.get("product_version_id")),
        document_type_id=_uuid_or_none(snapshot.get("document_type_id")),
    )


def _uuid_or_none(value) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        return None


def _validate_filters(db: Session, filters: QueryFilters) -> None:
    """过滤 ID 全部来自数据库目录；版本必须属于所选产品（DD-08 §11.1）。"""
    validate_retrieval_filters(
        db,
        RetrievalFilters(
            product_id=filters.product_id,
            version_ids=[filters.product_version_id] if filters.product_version_id else [],
            document_type_ids=[filters.document_type_id] if filters.document_type_id else [],
        ),
    )


# ---- 会话 CRUD ----

def create_conversation(db: Session, user: User, title: str | None, filters: QueryFilters | None) -> Conversation:
    filters = filters or QueryFilters()
    _validate_filters(db, filters)
    conversation = Conversation(
        user_id=user.id,
        title=(title or "").strip() or "新会话",
        status="ACTIVE",
        filters_snapshot=filters_to_snapshot(filters),
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def _get_owned_conversation(db: Session, user: User, conversation_id) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise ConversationError("CONVERSATION_NOT_FOUND", "会话不存在或已删除", status=404)
    return conversation


def get_conversation(db: Session, user: User, conversation_id) -> Conversation:
    conversation = _get_owned_conversation(db, user, conversation_id)
    if conversation.status == "DELETED":
        raise ConversationError("CONVERSATION_NOT_FOUND", "会话不存在或已删除", status=404)
    return conversation


def list_conversations(
    db: Session, user: User, *, include_archived: bool = False, limit: int = 50
) -> list[Conversation]:
    query = select(Conversation).where(
        Conversation.user_id == user.id,
        Conversation.status != "DELETED",
    )
    if not include_archived:
        query = query.where(Conversation.status == "ACTIVE")
    query = query.order_by(Conversation.last_message_at.desc(), Conversation.created_at.desc()).limit(limit)
    return list(db.execute(query).scalars())


def update_conversation(
    db: Session, user: User, conversation_id, title: str | None, filters: QueryFilters | None
) -> Conversation:
    conversation = _get_owned_conversation(db, user, conversation_id)
    if conversation.status == "DELETED":
        raise ConversationError("CONVERSATION_NOT_FOUND", "会话不存在或已删除", status=404)
    if title is not None:
        conversation.title = title.strip() or conversation.title
    if filters is not None:
        _validate_filters(db, filters)
        conversation.filters_snapshot = filters_to_snapshot(filters)
    db.commit()
    db.refresh(conversation)
    return conversation


def set_conversation_status(db: Session, user: User, conversation_id, status: str) -> Conversation:
    conversation = _get_owned_conversation(db, user, conversation_id)
    conversation.status = status
    conversation.deleted_at = _now() if status == "DELETED" else None
    db.commit()
    db.refresh(conversation)
    return conversation


# ---- 提问事务（DD-10 §3） ----

def create_question(
    db: Session, user: User, conversation_id, content: str, filters: QueryFilters | None
) -> CreateMessageResult:
    conversation = db.execute(
        select(Conversation).where(Conversation.id == conversation_id).with_for_update()
    ).scalar_one_or_none()
    if conversation is None or conversation.user_id != user.id:
        raise ConversationError("CONVERSATION_NOT_FOUND", "会话不存在或已删除", status=404)
    if conversation.status != "ACTIVE":
        raise ConversationError(
            "CONVERSATION_NOT_ACTIVE", "会话已归档或删除，不能继续提问", status=409
        )

    recover_stale_answers(db, conversation.id)

    open_answer = db.execute(
        select(Answer)
        .where(Answer.conversation_id == conversation.id, Answer.status.in_(_OPEN_STATUSES))
        .limit(1)
    ).scalars().first()
    if open_answer is not None:
        raise ConversationError(
            "ANSWER_ALREADY_IN_PROGRESS", "该会话已有回答正在生成，请稍候", status=409
        )

    question = (content or "").strip()
    if not question:
        raise ConversationError("EMPTY_QUESTION", "问题不能为空", status=400)
    if len(question) > _MAX_QUESTION_CHARS:
        raise ConversationError("QUESTION_TOO_LONG", "问题过长（上限 4000 字符）", status=400)

    # filters 省略→用会话当前条件；出现→完整替换
    effective = filters if filters is not None else filters_from_snapshot(conversation.filters_snapshot)
    _validate_filters(db, effective)

    message = Message(conversation_id=conversation.id, role="user", content=question)
    db.add(message)
    db.flush()
    answer = Answer(
        conversation_id=conversation.id,
        message_id=message.id,
        user_id=user.id,
        status="PENDING",
        degradation_flags=[],
    )
    db.add(answer)
    db.flush()

    now = _now()
    conversation.last_message_at = now
    conversation.filters_snapshot = filters_to_snapshot(effective)
    if conversation.title == "新会话" and question:
        conversation.title = question[:20]

    db.add(
        ProcessingTask(
            task_type="GENERATE_ANSWER",
            status="PENDING",
            idempotency_key=f"answer:{answer.id}:stage:generate_answer",
            scheduled_at=now,
            source_id=None,
            version_id=None,
            payload={"answer_id": str(answer.id)},
            priority=50,
            max_attempts=3,
            created_by_user_id=user.id,
        )
    )
    db.commit()
    return CreateMessageResult(
        message_id=message.id,
        answer_id=answer.id,
        status=answer.status,
        events_url=f"/api/v1/answers/{answer.id}/events",
    )


# ---- 消息与回答读取 ----

def get_answer(db: Session, user: User, answer_id) -> Answer:
    recover_stale_answers(db)
    db.commit()
    answer = db.get(Answer, answer_id)
    if answer is None or answer.user_id != user.id:
        raise ConversationError("ANSWER_NOT_FOUND", "回答不存在", status=404)
    return answer


def list_messages(db: Session, user: User, conversation_id) -> list[MessageOut]:
    conversation = _get_owned_conversation(db, user, conversation_id)
    if conversation.status == "DELETED":
        raise ConversationError("CONVERSATION_NOT_FOUND", "会话不存在或已删除", status=404)
    recover_stale_answers(db, conversation.id)
    db.commit()
    messages = list(
        db.execute(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at, Message.id)
        ).scalars()
    )
    answers = {
        a.message_id: a
        for a in db.execute(
            select(Answer).where(Answer.conversation_id == conversation.id)
        ).scalars()
    }
    answer_ids = [a.id for a in answers.values()]
    citations_by_answer: dict[uuid.UUID, list[AnswerCitation]] = defaultdict(list)
    availability_by_source: dict[uuid.UUID, str] = {}
    if answer_ids:
        citation_rows = list(
            db.execute(
                select(AnswerCitation)
                .where(AnswerCitation.answer_id.in_(answer_ids))
                .order_by(AnswerCitation.answer_id, AnswerCitation.citation_no)
            ).scalars()
        )
        citations_by_answer = defaultdict(list)
        for citation in citation_rows:
            citations_by_answer[citation.answer_id].append(citation)
        source_ids = {c.source_id for c in citation_rows if c.source_id is not None}
        if source_ids:
            sources = {
                source.id: source
                for source in db.execute(
                    select(KnowledgeSource).where(KnowledgeSource.id.in_(source_ids))
                ).scalars()
            }
            availability_by_source = {
                source_id: ("SOURCE_OFFLINE" if source.status == "OFFLINE" else "AVAILABLE")
                for source_id, source in sources.items()
            }
    out: list[MessageOut] = []
    for message in messages:
        out.append(
            MessageOut(
                id=str(message.id),
                conversation_id=conversation.id,
                role="user",
                content=message.content,
                answer=None,
                created_at=message.created_at,
            )
        )
        answer = answers.get(message.id)
        if answer is not None:
            out.append(
                MessageOut(
                    id=f"answer-{answer.id}",
                    conversation_id=conversation.id,
                    role="assistant",
                    content=answer.summary or "",
                    answer=_build_answer_out_from_citations(
                        answer,
                        citations_by_answer.get(answer.id, []),
                        availability_by_source,
                    ),
                    created_at=answer.created_at,
                )
            )
    return out


def _build_answer_out_from_citations(
    answer: Answer,
    citations: list[AnswerCitation],
    availability_by_source: dict[uuid.UUID, str],
) -> AnswerOut:
    grouped_citations, citation_no_map = _group_citations(
        citations,
        availability_by_source=availability_by_source,
    )
    return AnswerOut(
        id=answer.id,
        status=answer.status,
        progress_stage=answer.progress_stage,
        answer_type=answer.answer_type,
        summary=answer.summary,
        blocks=_answer_blocks(answer, citation_no_map),
        citations=grouped_citations,
        degradation_flags=list(answer.degradation_flags or []),
        error_code=answer.error_code,
        error_summary=answer.error_summary,
        created_at=answer.created_at,
        completed_at=answer.completed_at,
    )


def build_answer_out(db: Session, answer: Answer) -> AnswerOut:
    raw_citations = list(
        db.execute(
            select(AnswerCitation)
            .where(AnswerCitation.answer_id == answer.id)
            .order_by(AnswerCitation.citation_no)
        ).scalars()
    )
    citations, citation_no_map = _group_citations(raw_citations, db=db)
    return AnswerOut(
        id=answer.id,
        status=answer.status,
        progress_stage=answer.progress_stage,
        answer_type=answer.answer_type,
        summary=answer.summary,
        blocks=_answer_blocks(answer, citation_no_map),
        citations=citations,
        degradation_flags=list(answer.degradation_flags or []),
        error_code=answer.error_code,
        error_summary=answer.error_summary,
        created_at=answer.created_at,
        completed_at=answer.completed_at,
    )


def _citation_out(
    db: Session | None,
    citation: AnswerCitation,
    *,
    availability: str | None = None,
) -> AnswerCitationOut:
    location = CitationLocationOut(
        chunk_id=citation.chunk_id,
        heading_path=list(citation.heading_path or []),
        locator=citation.locator_json or {},
        excerpt=citation.excerpt,
    )
    return AnswerCitationOut(
        citation_no=citation.citation_no,
        source_id=citation.source_id,
        version_id=citation.version_id,
        document_title=citation.document_title,
        document_type=citation.document_type_code,
        heading_path=location.heading_path,
        version_label=citation.version_label,
        source_updated_at=citation.source_updated_at,
        excerpt=citation.excerpt,
        original_url=citation.original_url,
        availability=availability or _citation_availability(db, citation),
        support_count=1,
        locations=[location],
    )


def _citation_group_key(citation: AnswerCitation) -> tuple[str, str, str]:
    """按稳定的来源+版本聚合，不能按标题聚合。"""
    if citation.source_id is not None or citation.version_id is not None:
        return (
            "document",
            str(citation.source_id or ""),
            str(citation.version_id or ""),
        )
    # 删除后的历史引用仍需保持独立，避免无来源引用被误合并。
    return ("row", str(citation.id), "")


def _group_citations(
    citations: list[AnswerCitation],
    *,
    db: Session | None = None,
    availability_by_source: dict[uuid.UUID, str] | None = None,
) -> tuple[list[AnswerCitationOut], dict[int, int]]:
    """保留 chunk 级证据，同时把接口输出聚合为文档版本级来源。"""
    groups: list[list[AnswerCitation]] = []
    group_by_key: dict[tuple[str, str, str], int] = {}
    citation_no_map: dict[int, int] = {}
    for citation in citations:
        key = _citation_group_key(citation)
        group_index = group_by_key.get(key)
        if group_index is None:
            group_index = len(groups)
            group_by_key[key] = group_index
            groups.append([])
        groups[group_index].append(citation)
        citation_no_map[citation.citation_no] = group_index + 1

    output: list[AnswerCitationOut] = []
    for group_no, rows in enumerate(groups, start=1):
        first = rows[0]
        if availability_by_source is not None:
            availability = availability_by_source.get(
                first.source_id,
                "SOURCE_DELETED" if first.source_id is None else "SOURCE_DELETED",
            )
        else:
            availability = _citation_availability(db, first) if db is not None else "SOURCE_DELETED"
        locations = [
            CitationLocationOut(
                chunk_id=row.chunk_id,
                heading_path=list(row.heading_path or []),
                locator=row.locator_json or {},
                excerpt=row.excerpt,
            )
            for row in rows
        ]
        output.append(
            AnswerCitationOut(
                citation_no=group_no,
                source_id=first.source_id,
                version_id=first.version_id,
                document_title=first.document_title,
                document_type=first.document_type_code,
                heading_path=list(first.heading_path or []),
                version_label=first.version_label,
                source_updated_at=first.source_updated_at,
                excerpt=first.excerpt,
                original_url=first.original_url,
                availability=availability,
                support_count=len(rows),
                locations=locations,
            )
        )
    return output, citation_no_map


def _answer_blocks(answer: Answer, citation_no_map: dict[int, int]) -> list[AnswerBlock]:
    """将持久化的 chunk 引用编号映射为接口返回的来源组编号。"""
    blocks: list[AnswerBlock] = []
    for raw_block in answer.blocks_json or []:
        if not isinstance(raw_block, dict):
            continue
        block = dict(raw_block)
        mapped: list[int] = []
        for raw_no in block.get("citation_nos") or []:
            try:
                group_no = citation_no_map.get(int(raw_no))
            except (TypeError, ValueError):
                continue
            if group_no is not None and group_no not in mapped:
                mapped.append(group_no)
        block["citation_nos"] = mapped
        blocks.append(AnswerBlock.model_validate(block))
    return blocks


def _citation_availability(db: Session, citation: AnswerCitation) -> str:
    if citation.source_id is None:
        return "SOURCE_DELETED"
    source = db.get(KnowledgeSource, citation.source_id)
    if source is None:
        return "SOURCE_DELETED"
    if source.status == "OFFLINE":
        return "SOURCE_OFFLINE"
    return "AVAILABLE"


def citation_detail(db: Session, user: User, answer_id, citation_no) -> CitationDetailOut:
    answer = get_answer(db, user, answer_id)
    raw_citations = list(db.execute(
        select(AnswerCitation).where(
            AnswerCitation.answer_id == answer.id,
        ).order_by(AnswerCitation.citation_no)
    ).scalars())
    grouped_citations, _ = _group_citations(raw_citations, db=db)
    citation = next(
        (item for item in grouped_citations if item.citation_no == citation_no),
        None,
    )
    if citation is None:
        raise ConversationError("CITATION_NOT_FOUND", "引用不存在", status=404)
    first_location = citation.locations[0] if citation.locations else CitationLocationOut()
    return CitationDetailOut(
        citation_no=citation.citation_no,
        source_id=citation.source_id,
        version_id=citation.version_id,
        document_title=citation.document_title,
        document_type=citation.document_type,
        heading_path=list(first_location.heading_path),
        locator=first_location.locator,
        excerpt=citation.excerpt,
        original_url=citation.original_url,
        availability=citation.availability,
        support_count=citation.support_count,
        locations=citation.locations,
    )


# ---- 取消与反馈 ----

def request_cancel(db: Session, user: User, answer_id) -> Answer:
    """请求中止回答（DD-08 §11.1 API-QA-004）。

    未终结回答置 cancel_requested，Worker 在阶段边界转 CANCELED；
    已终结回答返回当前状态（幂等）。
    """
    answer = get_answer(db, user, answer_id)
    if answer.status in _OPEN_STATUSES:
        answer.cancel_requested = True
        db.commit()
        db.refresh(answer)
    return answer


def upsert_feedback(db: Session, user: User, answer_id, data: FeedbackIn) -> None:
    answer = get_answer(db, user, answer_id)
    if answer.status != "SUCCEEDED":
        raise ConversationError("FEEDBACK_ONLY_ON_SUCCEEDED", "只有已完成的回答可以反馈", status=409)
    feedback = db.get(AnswerFeedback, (answer.id, user.id))
    if feedback is None:
        db.add(
            AnswerFeedback(
                answer_id=answer.id,
                user_id=user.id,
                rating=data.rating,
                reason_codes=list(data.reason_codes or []),
                comment=data.comment,
            )
        )
    else:
        feedback.rating = data.rating
        feedback.reason_codes = list(data.reason_codes or [])
        feedback.comment = data.comment
    db.commit()
