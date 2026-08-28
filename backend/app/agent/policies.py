"""路由、证据、预算与循环上限策略（DD-21 §6/§7/§9/§10）。

本地策略对模型路由进行二次约束：ANSWER/SUMMARIZE/RELATE 不得被模型错误标记为无须检索；
EXPLAIN 带内部实体或过滤器时强制检索；解析失败时保守路由。
"""

from __future__ import annotations

import re

from ..core.config import get_settings
from .errors import AGENT_STEP_LIMIT_EXCEEDED, AGENT_TIMEOUT
from .state import (
    EVIDENCE_INSUFFICIENT,
    EVIDENCE_PARTIAL,
    EVIDENCE_SUFFICIENT,
    EVIDENCE_UNAVAILABLE,
    AgentState,
)

# 必须检索的操作（DD-21 §6.1）
ALWAYS_RETRIEVE = ("ANSWER", "SUMMARIZE", "RELATE")
# EXPLAIN 触发检索的内部实体类型
EXPLAIN_RETRIEVAL_ENTITY_TYPES = {"product", "model", "version", "产品", "型号", "版本"}

_GREETING_PREFIX_RE = re.compile(
    r"^\s*(?:hello|hi|hey|你好|您好|早上好|下午好|晚上好)"
    r"\s*[,，、:：.!！?？;；\-—]*\s*",
    re.IGNORECASE,
)
_NON_KNOWLEDGE_CHAT = {
    "谢谢", "感谢", "多谢", "你是谁", "你是什么", "你是什么模型",
    "介绍一下你", "怎么使用", "怎么用", "你能做什么", "你会什么", "你叫什么",
    "你好吗", "你怎么了",
}
_KNOWLEDGE_QUERY_MARKERS = (
    "介绍", "产品", "版本", "型号", "规格", "参数", "配置", "部署", "安装",
    "功能", "内存", "磁盘", "吞吐", "接口", "策略", "漏洞", "文档", "案例",
    "故障", "问题", "告警", "修复", "支持", "区别", "对比", "资料", "说明",
    "哪些", "多少", "如何", "怎么",
)


def strip_greeting_prefix(question: str) -> str:
    """移除问题开头的礼貌问候，保留后续可检索内容。"""
    return _GREETING_PREFIX_RE.sub("", question or "", count=1).strip()


def looks_like_knowledge_question(question: str) -> bool:
    """识别被问候前缀或模型 CHAT 误判掩盖的知识查询。

    这是路由兜底，不替代模型意图理解：只在文本包含明确知识/企业资料信号时
    触发，避免把纯问候、感谢和询问助手身份送入 RAG。
    """
    text = strip_greeting_prefix(question)
    if not text:
        return False
    normalized = re.sub(r"[？?。！!]+$", "", text).strip().lower()
    if normalized in {item.lower() for item in _NON_KNOWLEDGE_CHAT}:
        return False
    return any(marker in text for marker in _KNOWLEDGE_QUERY_MARKERS)


def local_requires_retrieval(
    operation: str,
    *,
    query_entities: list[dict],
    filters_snapshot: dict,
    memory_entities: list[dict],
) -> tuple[bool, str]:
    """本地二次约束：决定 requires_retrieval 与 reason_code。"""
    if operation in ALWAYS_RETRIEVE:
        return True, "REQUIRED_OPERATION"
    if operation in ("CHAT", "CLARIFY"):
        return False, "NON_KNOWLEDGE"
    if operation == "EXPLAIN":
        if any(filters_snapshot.get(k) for k in ("product_id", "product_version_id", "document_type_id")):
            return True, "FILTER_SCOPE"
        internal_entities = [
            e for e in (query_entities or [])
            if e.get("entity_type", "").lower() in EXPLAIN_RETRIEVAL_ENTITY_TYPES
        ]
        entity_values = [e.get("value") for e in (query_entities or [])]
        memory_vals = [e.get("value") for e in (memory_entities or [])]
        if internal_entities or _looks_internal(entity_values + memory_vals):
            return True, "INTERNAL_ENTITY"
        return False, "GENERAL_EXPLAIN"
    # 未知操作保守检索
    return True, "UNKNOWN_OPERATION_CONSERVATIVE"


def _looks_internal(values: list[str]) -> bool:
    """实体值含产品/型号/版本特征（AE 前缀、V 版本号、型号号段）时视为内部对象。"""
    for value in values:
        v = str(value or "")
        if not v:
            continue
        if v.upper().startswith("AE") or "ae" in v.lower():
            return True
        if len(v) >= 3 and v[:1].isupper() and any(ch.isdigit() for ch in v[1:]):
            return True
    return False


def check_limits(state: AgentState, ctx) -> dict | None:
    """节点进入前检查步数上限/截止时间/取消。返回终止增量或 None。"""
    settings = ctx.settings
    if state.get("step_count", 0) >= settings.agent_max_steps:
        return {
            "_terminate": True,
            "final_status": "FAILED",
            "error_code": AGENT_STEP_LIMIT_EXCEEDED,
            "error_summary": "回答流程超过安全步数上限",
        }
    if ctx.clock().timestamp() > ctx.deadline:
        return {
            "_terminate": True,
            "final_status": "FAILED",
            "error_code": AGENT_TIMEOUT,
            "error_summary": "回答处理超时",
        }
    if _answer_canceled(state, ctx):
        return {
            "_terminate": True,
            "final_status": "CANCELED",
            "error_code": "AGENT_CANCELED",
            "error_summary": "用户已取消回答",
        }
    return None


def _answer_canceled(state: AgentState, ctx) -> bool:
    if state.get("cancel_requested"):
        return True
    from ..db.models.conversation import Answer

    try:
        with ctx.session_factory() as db:
            answer = db.get(Answer, state["answer_id"])
            return bool(
                answer is not None and (answer.cancel_requested or answer.status == "CANCELED")
            )
    except Exception:  # noqa: BLE001 读取失败按未取消处理
        return bool(state.get("cancel_requested"))


# ---- 条件边路由 ----

def route_after_load(state: AgentState) -> str:
    if state.get("_terminate") or state.get("final_status"):
        return "persist_result"
    return "build_context"


def route_after_goal(state: AgentState) -> str:
    """Select direct, clarification or bounded tool planning path."""
    if state.get("_terminate"):
        return "persist_result"
    decision = (state.get("goal") or {}).get("decision")
    if decision == "CLARIFY":
        return "finalize_clarification"
    if decision == "RESPOND":
        return "generate_general"
    mode = state.get("execution_mode")
    if mode == "CLARIFY":
        return "finalize_clarification"
    if mode == "DIRECT":
        return "generate_general"
    if (state.get("goal") or {}).get("operation") == "IDENTITY":
        return "answer_identity"
    return "create_plan"


def route_after_tool(state: AgentState) -> str:
    if state.get("_terminate"):
        return "persist_result"
    verification = state.get("verification_result") or {}
    if verification.get("needs_replan") and state.get("replan_count", 0) < get_settings().agent_max_replans:
        return "create_plan"
    # For non-RAG tools, let the LLM choose the next action after every
    # observation. Knowledge retrieval keeps its dedicated evidence pipeline.
    observations = state.get("observations") or []
    last_tool = observations[-1].get("tool_name") if observations else None
    if (
        state.get("tool_agent_enabled")
        and observations
        and last_tool not in ("knowledge.search", "skill.load")
        and observations[-1].get("status") == "SUCCEEDED"
        and state.get("replan_count", 0) < get_settings().agent_max_replans
    ):
        return "create_plan"
    pending = [step for step in state.get("plan_steps", []) if step.get("status") in ("PENDING", "READY")]
    if pending:
        done = {step.get("id") for step in state.get("plan_steps", []) if step.get("status") == "SUCCEEDED"}
        if any(set(step.get("depends_on") or []).issubset(done) for step in pending):
            return "execute_tool"
    observations = state.get("observations") or []
    if observations and observations[-1].get("tool_name") == "skill.load":
        return "generate_general"
    return "assess_evidence"


def route_after_evidence(state: AgentState) -> str:
    if state.get("_terminate"):
        return "persist_result"
    quality = state.get("evidence_quality", EVIDENCE_INSUFFICIENT)
    evidence = state.get("evidence", []) or []
    if quality == EVIDENCE_UNAVAILABLE:
        return "persist_result"  # assess 已置终止失败
    if not evidence or quality == EVIDENCE_INSUFFICIENT:
        return "finalize_insufficient"
    if quality == EVIDENCE_PARTIAL and state.get("query_rewrite_count", 0) < get_settings().agent_query_rewrite_limit:
        return "rewrite_query"
    return "generate_grounded"


def route_after_validation(state: AgentState) -> str:
    if state.get("_terminate"):
        return "persist_result"
    errors = state.get("validation_errors", []) or []
    if not errors:
        return "update_memory"
    if state.get("citation_repair_count", 0) < get_settings().agent_citation_repair_limit:
        return "generate_grounded"
    return "finalize_insufficient"


# ---- 证据评估 ----

def assess_evidence(evidence: list[dict], retrieval_status: str, degradation_flags: list[str]) -> str:
    """本地为主：SUFFICIENT/PARTIAL/INSUFFICIENT；检索依赖不可用时 UNAVAILABLE。"""
    if "BM25_FAILED" in degradation_flags or "SEARCH_UNAVAILABLE" in degradation_flags:
        return EVIDENCE_UNAVAILABLE
    if not evidence:
        return EVIDENCE_INSUFFICIENT
    if retrieval_status == "SUFFICIENT":
        return EVIDENCE_SUFFICIENT
    return EVIDENCE_PARTIAL
