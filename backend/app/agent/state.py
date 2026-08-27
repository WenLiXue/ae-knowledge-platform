"""AgentState 与序列化 DTO（DD-21 §5）。

AgentState 是可 JSON 序列化的 TypedDict：只保存本轮预算选中的有限上下文，
不保存 SQLAlchemy Session、模型客户端、检索服务实例或密钥。
不使用 add_messages 累积全量消息——项目已有自己的消息/答案/引用领域模型。
"""

from __future__ import annotations

import uuid
from typing import TypedDict

# 意图操作（DD-21 §6.1）
OPERATIONS = ("CHAT", "CLARIFY", "ANSWER", "SUMMARIZE", "RELATE", "EXPLAIN")

# 证据质量（DD-21 §10.1）
EVIDENCE_SUFFICIENT = "SUFFICIENT"
EVIDENCE_PARTIAL = "PARTIAL"
EVIDENCE_CONFLICTING = "CONFLICTING"
EVIDENCE_INSUFFICIENT = "INSUFFICIENT"
EVIDENCE_UNAVAILABLE = "UNAVAILABLE"
EVIDENCE_QUALITIES = (
    EVIDENCE_SUFFICIENT,
    EVIDENCE_PARTIAL,
    EVIDENCE_CONFLICTING,
    EVIDENCE_INSUFFICIENT,
    EVIDENCE_UNAVAILABLE,
)

# 终态
FINAL_SUCCEEDED = "SUCCEEDED"
FINAL_FAILED = "FAILED"
FINAL_CANCELED = "CANCELED"


class AgentState(TypedDict, total=False):
    """单次 answer run 的完整状态。所有字段必须可 JSON 序列化。"""

    # 身份与幂等
    run_id: str
    answer_id: str
    conversation_id: str
    user_id: str
    graph_version: str
    # 当前问题所在消息（构建上下文时排除本轮；AgentRun 水位）
    current_message_id: str | None

    # 输入
    question: str
    filters_snapshot: dict
    cancel_requested: bool

    # 会话上下文
    recent_turns: list[dict]
    memory_summary: str
    memory_entities: list[dict]
    memory_constraints: list[str]
    unresolved_topics: list[str]
    context_token_estimate: int

    # 查询理解与路由
    goal: dict
    execution_mode: str
    completion_criteria: list[dict]
    operation: str
    normalized_question: str
    requires_retrieval: bool
    clarification_question: str | None
    query_entities: list[str]
    route_reason_code: str

    # 工具型 Agent 计划与观察（全部为可 JSON 序列化 DTO）
    plan_id: str | None
    plan_revision: int
    plan_steps: list[dict]
    active_step_id: str | None
    observations: list[dict]
    pending_approval_id: str | None
    suspended_reason: str | None
    tool_call_count: int
    replan_count: int
    verification_result: dict | None

    # 检索
    retrieval_run_id: str | None
    retrieval_queries: list[str]
    evidence: list[dict]
    evidence_quality: str
    evidence_status_raw: str
    retrieval_config_revision: int | None
    degradation_flags: list[str]

    # 生成与校验
    answer_text: str
    answer_summary: str
    answer_type: str
    answer_confidence: str
    answer_blocks: list[dict]
    model_key: str | None
    citation_drafts: list[dict]
    validation_errors: list[str]

    # 有界循环计数器（恢复后不得重置）
    step_count: int
    intent_repair_count: int
    query_rewrite_count: int
    citation_repair_count: int
    memory_repair_count: int

    # 记忆更新与终态
    memory_patch: dict
    final_status: str
    error_code: str | None
    error_summary: str | None
    node_trace: list[dict]

    # 内部运行标记（终止路由用；可 JSON 序列化）
    _terminate: bool


def build_initial_state(
    *,
    answer_id: str,
    conversation_id: str,
    user_id: str,
    run_id: str,
    graph_version: str,
    question: str = "",
    filters_snapshot: dict | None = None,
    cancel_requested: bool = False,
) -> AgentState:
    """构造初始状态：只含身份/幂等字段，其余由节点逐步填充。"""
    return {
        "run_id": run_id,
        "answer_id": str(answer_id),
        "conversation_id": str(conversation_id),
        "user_id": str(user_id),
        "graph_version": graph_version,
        "question": question,
        "filters_snapshot": filters_snapshot or {},
        "cancel_requested": bool(cancel_requested),
        "operation": "",
        "goal": {},
        "execution_mode": "LEGACY_RAG",
        "completion_criteria": [],
        "requires_retrieval": False,
        "evidence": [],
        "degradation_flags": [],
        "retrieval_queries": [],
        "query_entities": [],
        "plan_id": None,
        "plan_revision": 0,
        "plan_steps": [],
        "active_step_id": None,
        "observations": [],
        "pending_approval_id": None,
        "suspended_reason": None,
        "tool_call_count": 0,
        "replan_count": 0,
        "verification_result": None,
        "validation_errors": [],
        "citation_drafts": [],
        "node_trace": [],
        "recent_turns": [],
        "memory_entities": [],
        "memory_constraints": [],
        "unresolved_topics": [],
        "step_count": 0,
        "intent_repair_count": 0,
        "query_rewrite_count": 0,
        "citation_repair_count": 0,
        "memory_repair_count": 0,
    }


def evidence_to_dict(evidence) -> dict:
    """EvidenceItem → 可 JSON 序列化 dict（截断超长正文，DD-21 §5.1）。"""
    content = evidence.content or ""
    if len(content) > 4000:
        content = content[:4000] + "…"
    return {
        "evidence_id": evidence.evidence_id,
        "chunk_id": str(evidence.chunk_id),
        "source_id": str(evidence.source_id) if evidence.source_id else None,
        "document_version_id": str(evidence.document_version_id) if evidence.document_version_id else None,
        "content": content,
        "title": evidence.title,
        "heading_path": list(evidence.heading_path or []),
        "locator": evidence.locator or {},
        "source_priority": evidence.source_priority or 0,
        "source_updated_at": (
            evidence.source_updated_at.isoformat() if evidence.source_updated_at else None
        ),
    }


def make_run_id() -> str:
    return str(uuid.uuid4())
