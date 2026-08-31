"""会话、问答、检索运行与候选数据模型（DD-19 §5.4）。

- conversations / messages / answers / answer_citations / answer_feedback：
  会话与问答持久化（DD-10、DD-08 §10-14）；
- retrieval_runs：一次检索运行的记录（模式、降级 flag、配置 revision、阶段耗时、
  候选数量、证据状态）；正文不重复保存；
- retrieval_candidates：Top-K 候选明细（各阶段 rank/分数、是否进入最终证据及
  排除原因），(retrieval_run_id, chunk_id) 唯一。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CHAR,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from .mixins import TimestampMixin


class RetrievalRun(Base, TimestampMixin):
    """conversation.retrieval_runs —— 一次检索运行记录（DD-19 §5.4）。"""

    __tablename__ = "retrieval_runs"
    __table_args__ = (
        Index("ix_retrieval_runs_created", "created_at"),
        {"schema": "conversation", "comment": "检索运行记录"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_question: Mapped[str] = mapped_column(Text, nullable=False)
    query_texts: Mapped[list | None] = mapped_column(JSONB, nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge.products.id"), nullable=True
    )
    version_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    document_type_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # HYBRID / BM25_ONLY / FAILED（双召回失败记录 FAILED 不生成答案）
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    degradation_flags: Mapped[list | None] = mapped_column(ARRAY(String), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="SUCCEEDED", server_default="SUCCEEDED"
    )
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    config_revision: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    embedding_model_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rerank_model_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    params_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    stage_duration_ms: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    candidate_counts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # SUFFICIENT / PARTIAL / INSUFFICIENT（确定性信号，供 Phase 6 证据充分度判断）
    evidence_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence_count: Mapped[int | None] = mapped_column(Integer, nullable=True)


class RetrievalCandidate(Base, TimestampMixin):
    """conversation.retrieval_candidates —— 检索候选明细（DD-19 §5.4）。"""

    __tablename__ = "retrieval_candidates"
    __table_args__ = (
        Index("uq_retrieval_candidates_run_chunk", "retrieval_run_id", "chunk_id", unique=True),
        Index("ix_retrieval_candidates_run", "retrieval_run_id"),
        {"schema": "conversation", "comment": "检索候选"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    retrieval_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation.retrieval_runs.id"), nullable=False
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge.document_chunks.id"), nullable=False
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge.knowledge_sources.id"), nullable=True
    )
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge.document_versions.id"), nullable=True
    )
    ordinal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    bm25_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vector_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bm25_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    vector_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rrf_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rerank_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_evidence: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    evidence_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exclusion_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    score_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    title_snapshot: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)


class Conversation(Base, TimestampMixin):
    """conversation.conversations —— 会话（DD-10 §2）。"""

    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_user_updated", "user_id", "updated_at"),
        {"schema": "conversation", "comment": "会话"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth.users.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(
        String(512), nullable=False, default="新会话", server_default="新会话"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ACTIVE", server_default="ACTIVE"
    )
    filters_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Message(Base, TimestampMixin):
    """conversation.messages —— 消息（不物理覆盖历史）。"""

    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        {"schema": "conversation", "comment": "消息"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation.conversations.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)


class Answer(Base, TimestampMixin):
    """conversation.answers —— 回答（DD-10 §4 状态机）。

    同一会话最多一个 PENDING/WAITING/RETRIEVING/STREAMING 回答（部分唯一索引兜底）。
    """

    __tablename__ = "answers"
    __table_args__ = (
        Index("ix_answers_conversation_created", "conversation_id", "created_at"),
        Index(
            "uq_answer_open_per_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'WAITING', 'RETRIEVING', 'STREAMING')"),
        ),
        {"schema": "conversation", "comment": "回答"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation.conversations.id"), nullable=False
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation.messages.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth.users.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PENDING", server_default="PENDING"
    )
    progress_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    answer_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    draft_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    blocks_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    degradation_flags: Mapped[list | None] = mapped_column(ARRAY(String), nullable=False)
    retrieval_config_revision: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    retrieval_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation.retrieval_runs.id"), nullable=True
    )
    model_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    index_generation: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AnswerCitation(Base, TimestampMixin):
    """conversation.answer_citations —— 回答引用快照（DD-10 §6）。

    保存生成时的最小必要快照，来源后续下线/更新不替换历史引用。
    """

    __tablename__ = "answer_citations"
    __table_args__ = (
        Index("ix_answer_citations_answer_no", "answer_id", "citation_no"),
        {"schema": "conversation", "comment": "回答引用"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    answer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation.answers.id"), nullable=False
    )
    citation_no: Mapped[int] = mapped_column(Integer, nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge.knowledge_sources.id"), nullable=True
    )
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge.document_versions.id"), nullable=True
    )
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge.document_chunks.id"), nullable=True
    )
    document_title: Mapped[str] = mapped_column(String(512), nullable=False)
    document_type_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    version_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    heading_path: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    locator_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AnswerFeedback(Base, TimestampMixin):
    """conversation.answer_feedback —— 回答反馈（(answer_id, user_id) 唯一、幂等更新）。"""

    __tablename__ = "answer_feedback"
    __table_args__ = (
        {"schema": "conversation", "comment": "回答反馈"},
    )

    answer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation.answers.id"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth.users.id"), primary_key=True
    )
    rating: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_codes: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class ConversationMemory(Base, TimestampMixin):
    """conversation.conversation_memories —— 会话滚动记忆（DD-21 §8/§13）。

    只保存摘要/实体/约束/待解决主题等派生记忆，不保存原始正文；
    原始消息永不因摘要而删除。revision 为乐观锁，冲突时重读合并一次。
    """

    __tablename__ = "conversation_memories"
    __table_args__ = ({"schema": "conversation", "comment": "会话滚动记忆"},)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation.conversations.id"), primary_key=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    entities: Mapped[list | None] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    constraints: Mapped[list | None] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    unresolved_topics: Mapped[list | None] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    last_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation.messages.id"), nullable=True
    )
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")


class AgentRun(Base, TimestampMixin):
    """conversation.agent_runs —— LangGraph Agent 运行记录（DD-21 §13）。

    每次 answer 对应一条 AgentRun（answer_id 唯一）；checkpoint_thread_id 等于 answer_id。
    timings/token_usage 只保存汇总，不保存提示词与证据正文。
    """

    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("uq_agent_runs_answer", "answer_id", unique=True),
        Index("ix_agent_runs_conversation", "conversation_id"),
        {"schema": "conversation", "comment": "Agent 运行记录"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    answer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation.answers.id"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation.conversations.id"), nullable=False
    )
    # PENDING / RUNNING / WAITING / SUCCEEDED / FAILED / CANCELED
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PENDING", server_default="PENDING"
    )
    graph_version: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str | None] = mapped_column(String(32), nullable=True)
    current_node: Mapped[str | None] = mapped_column(String(64), nullable=True)
    step_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=12, server_default="12")
    checkpoint_thread_id: Mapped[str] = mapped_column(String(128), nullable=False)
    degradation_flags: Mapped[list | None] = mapped_column(ARRAY(String), nullable=False, default=list)
    timings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    token_usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentPlan(Base, TimestampMixin):
    """conversation.agent_plans —— 可恢复的用户目标与执行计划。"""

    __tablename__ = "agent_plans"
    __table_args__ = (
        Index("ix_agent_plans_run", "run_id"),
        Index("uq_agent_plans_run_revision", "run_id", "revision", unique=True),
        {"schema": "conversation", "comment": "Agent 执行计划"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation.agent_runs.id"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="DRAFT", server_default="DRAFT")
    completion_criteria: Mapped[list | None] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")


class AgentPlanStep(Base, TimestampMixin):
    """conversation.agent_plan_steps —— 计划步骤状态和安全参数摘要。"""

    __tablename__ = "agent_plan_steps"
    __table_args__ = (
        Index("uq_agent_plan_steps_plan_key", "plan_id", "step_key", unique=True),
        Index("ix_agent_plan_steps_plan_status", "plan_id", "status"),
        {"schema": "conversation", "comment": "Agent 计划步骤"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation.agent_plans.id"), nullable=False
    )
    step_key: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    capability: Mapped[str] = mapped_column(String(128), nullable=False)
    dependencies: Mapped[list | None] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    risk: Mapped[str] = mapped_column(String(24), nullable=False, default="READ_ONLY", server_default="READ_ONLY")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING", server_default="PENDING")
    input_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentToolCall(Base, TimestampMixin):
    """conversation.agent_tool_calls —— 每次工具尝试的可审计、可恢复记录。"""

    __tablename__ = "agent_tool_calls"
    __table_args__ = (
        Index("ix_agent_tool_calls_run_created", "run_id", "created_at"),
        Index("uq_agent_tool_calls_step_attempt", "step_id", "attempt", unique=True),
        {"schema": "conversation", "comment": "Agent 工具调用"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation.agent_runs.id"), nullable=False
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation.agent_plans.id"), nullable=False
    )
    step_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation.agent_plan_steps.id"), nullable=False
    )
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    idempotency_key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    arguments_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    external_operation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AgentApproval(Base, TimestampMixin):
    """conversation.agent_approvals —— 绑定计划 revision 和参数 hash 的确认。"""

    __tablename__ = "agent_approvals"
    __table_args__ = (
        Index("ix_agent_approvals_run_status", "run_id", "status"),
        Index("ix_agent_approvals_expires", "expires_at"),
        {"schema": "conversation", "comment": "Agent 工具确认"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation.agent_runs.id"), nullable=False
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation.agent_plans.id"), nullable=False
    )
    step_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation.agent_plan_steps.id"), nullable=False
    )
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("auth.users.id"), nullable=False)
    decision_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("auth.users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING", server_default="PENDING")
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    arguments_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    impact_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
