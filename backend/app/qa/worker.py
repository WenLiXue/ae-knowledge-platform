"""Answer Worker（DD-08 §11、DD-10 §3-4）：GENERATE_ANSWER 任务处理器。

流程（事务边界：外部 HTTP——理解/检索/生成——不持有 DB 事务）：
1. 短事务：加载 Answer/Conversation/UserMessage，检查取消 → RETRIEVING/UNDERSTANDING，提交；
2. 查询理解（QA 模型；失败降级原问题 + QUERY_REWRITE_FAILED）；需澄清 → CLARIFICATION；
3. 构建 QueryPlan + 调用 Phase 5 RetrievalService 取证据；
4. 短事务：取消检查 → STREAMING/GENERATING，记录 retrieval_run 与降级 flag，提交；
5. 生成：无证据 → INSUFFICIENT（不调用模型）；有证据 → 真实 LLM（feature_real_qa）或
   确定性 mock 预览；
6. 单一事务：保存 Answer 最终内容 + 引用快照原子提交，SUCCEEDED。
模型不可用/生成失败 → Answer FAILED + PipelineError（按可重试性进入任务重试）。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import Settings, get_settings
from ..agent.errors import AgentError
from ..db.models.catalog import DocumentType, Product, ProductVersion
from ..db.models.conversation import Answer, AnswerCitation, Conversation, Message
from ..db.models.knowledge import FeishuSourceDetail
from ..db.models.rag import DocumentMetadata
from ..llm.runtime import resolve_service_model
from ..llm.service import LLMConfigError
from ..model_gateway import create_gateway
from ..model_gateway.errors import GatewayError
from ..retrieval.errors import RetrievalError
from ..retrieval.filters import validate_filters as validate_retrieval_filters
from ..retrieval.schemas import RetrievalFilters
from ..retrieval.service import RetrievalService, build_retrieval_service
from ..worker.pipeline import PipelineError
from .llm import (
    QaError,
    chat_with_retry,
    generate_answer,
    generate_general_answer,
    local_query_understanding,
    mock_general_answer,
    mock_generated_answer,
    understand_query,
    validate_generated,
)
from .schemas import GeneratedAnswer

logger = logging.getLogger(__name__)

_OPEN_STATUSES = ("PENDING", "RETRIEVING", "STREAMING")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _filters_text(db: Session, snapshot: dict) -> str:
    parts: list[str] = []
    if snapshot.get("product_id"):
        row = db.get(Product, uuid.UUID(str(snapshot["product_id"])))
        if row:
            parts.append(f"产品={row.name}")
    if snapshot.get("product_version_id"):
        row = db.get(ProductVersion, uuid.UUID(str(snapshot["product_version_id"])))
        if row:
            parts.append(f"版本={row.version_code}")
    if snapshot.get("document_type_id"):
        row = db.get(DocumentType, uuid.UUID(str(snapshot["document_type_id"])))
        if row:
            parts.append(f"类型={row.name}")
    return "；".join(parts)


def _retrieval_filters_from_snapshot(snapshot: dict) -> RetrievalFilters:
    def _u(value):
        return uuid.UUID(str(value)) if value else None

    return RetrievalFilters(
        product_id=_u(snapshot.get("product_id")),
        version_ids=[_u(snapshot.get("product_version_id"))] if snapshot.get("product_version_id") else [],
        document_type_ids=[_u(snapshot.get("document_type_id"))] if snapshot.get("document_type_id") else [],
    )


def _context_lines(db: Session, conversation_id, exclude_message_id) -> list[str]:
    rows = list(
        db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.id != exclude_message_id)
            .order_by(Message.created_at.desc())
            .limit(6)
        ).scalars()
    )
    rows.reverse()
    lines: list[str] = []
    for message in rows:
        lines.append(f"问：{message.content}")
        answer = db.execute(
            select(Answer).where(Answer.message_id == message.id)
        ).scalars().first()
        if answer is not None and answer.summary:
            lines.append(f"答：{answer.summary[:200]}")
    return lines


def _is_knowledge_explanation(understanding, conversation: Conversation) -> bool:
    """EXPLAIN 只有在带有企业实体或显式筛选条件时才回知识库核验。"""
    if understanding is None or understanding.operation != "EXPLAIN":
        return False
    if any(conversation.filters_snapshot.get(key) for key in ("product_id", "product_version_id", "document_type_id")):
        return True
    return any(
        entity.entity_type.lower() in {"product", "model", "version", "产品", "型号", "版本"}
        for entity in understanding.detected_entities
    )


def _requires_retrieval(understanding, conversation: Conversation) -> bool:
    """Knowledge Assistant Orchestrator 的最小路由策略。"""
    if understanding is None:
        return True  # 查询理解模型故障时保守降级到原有知识查询路径
    if understanding.operation in {"CHAT", "CLARIFY"}:
        return False
    if understanding.operation == "EXPLAIN":
        return _is_knowledge_explanation(understanding, conversation)
    return understanding.operation in {"ANSWER", "SUMMARIZE", "RELATE"}


# Agent 图可重试错误码（DD-21 §15：超时/检索不可用/生成/模型/checkpoint/内部）
_AGENT_RETRYABLE_CODES = {
    "AGENT_TIMEOUT",
    "RETRIEVAL_UNAVAILABLE",
    "GENERATION_FAILED",
    "MODEL_UNAVAILABLE",
    "CHECKPOINT_UNAVAILABLE",
    "INTERNAL_ERROR",
}


def run_generate_answer(
    session: Session,
    task,
    *,
    search=None,
    retrieval_service: RetrievalService | None = None,
    chat_fn=None,
    settings: Settings | None = None,
) -> str | None:
    """执行 GENERATE_ANSWER（薄适配器，DD-21 §12）。

    - agent_graph_enabled=True：走 LangGraph 知识助手（checkpoint 恢复）；
    - 否则走旧手写编排（回滚路径）。

    使用独立短会话（与分类阶段一致）：不提交/污染 WorkerRunner 外层
    `with session.begin()` 事务。返回 None（无后续阶段）。
    """
    settings = settings or get_settings()
    payload = task.payload or {}
    answer_id = payload.get("answer_id")
    if not answer_id:
        raise PipelineError("VALIDATION", "ANSWER_ID_MISSING", "答案任务缺少 answer_id", retryable=False)

    if settings.agent_graph_enabled:
        return _run_agent_flow(
            answer_id,
            search=search, retrieval_service=retrieval_service, chat_fn=chat_fn, settings=settings,
        )

    # ---- 旧手写编排（feature flag 关闭时的回滚路径） ----
    from ..db.session import SessionLocal

    with SessionLocal() as session:
        answer = session.get(Answer, uuid.UUID(str(answer_id)))
        if answer is None:
            raise PipelineError("NOT_FOUND", "ANSWER_NOT_FOUND", "答案不存在", retryable=False)
        return _run_generate_answer(
            session, answer,
            search=search, retrieval_service=retrieval_service, chat_fn=chat_fn, settings=settings,
        )


def _run_agent_flow(
    answer_id,
    *,
    search=None,
    retrieval_service: RetrievalService | None = None,
    chat_fn=None,
    settings: Settings | None = None,
) -> str | None:
    """LangGraph 知识助手薄适配器（DD-21 §12.1）。

    读取 answer → 构造初始 AgentState（只含身份）→ 以 answer_id 作 thread_id 调用图 →
    将类型化结果映射到现有 Worker 成功/失败/取消语义。
    """
    settings = settings or get_settings()
    from ..db.session import SessionLocal
    from ..agent.context import AgentModels
    from ..agent.runtime import (
        build_runtime_for_worker,
        create_checkpointer_or_none,
        run_agent,
    )
    from ..agent.state import build_initial_state, make_run_id

    with SessionLocal() as db:
        answer = db.get(Answer, uuid.UUID(str(answer_id)))
        if answer is None:
            raise PipelineError("NOT_FOUND", "ANSWER_NOT_FOUND", "答案不存在", retryable=False)
        if answer.cancel_requested or answer.status == "CANCELED":
            _mark_canceled(db, answer)
            return None
        conversation = db.get(Conversation, answer.conversation_id)
        message = db.get(Message, answer.message_id)
        question = message.content if message is not None else (answer.summary or "")
        initial_state = build_initial_state(
            answer_id=str(answer.id),
            conversation_id=str(answer.conversation_id),
            user_id=str(answer.user_id),
            run_id=make_run_id(),
            graph_version=settings.agent_graph_version,
            filters_snapshot=conversation.filters_snapshot if conversation else {},
            tool_agent_enabled=bool(settings.agent_tools_enabled and settings.agent_planner_enabled),
        )
        if settings.agent_log_payloads:
            # 受控调试采样：显式开启后记录完整提问与回答摘要，便于联调；
            # 不记录证据正文、提示词与密钥
            logger.info(
                "agent_run_start",
                extra={"answer_id": str(answer.id), "question": question},
            )

    def _svc_factory():
        return retrieval_service or build_retrieval_service(search=search)

    models = AgentModels(session_factory=SessionLocal, chat_fn=chat_fn)
    context = build_runtime_for_worker(
        settings=settings,
        session_factory=SessionLocal,
        retrieval_service_factory=_svc_factory,
        models=models,
    )
    checkpointer = create_checkpointer_or_none(settings)
    try:
        result = run_agent(initial_state, context=context, checkpointer=checkpointer, settings=settings)
    except AgentError as exc:
        raise PipelineError(exc.category, exc.code, exc.message, retryable=exc.retryable) from exc
    except GatewayError as exc:
        raise PipelineError(exc.category, exc.code, exc.message, retryable=exc.retryable) from exc
    except LLMConfigError as exc:
        raise PipelineError("CONFIG", exc.code, exc.message, retryable=False) from exc
    except Exception as exc:  # noqa: BLE001
        raise PipelineError(
            "INTERNAL", "INTERNAL_ERROR", f"Agent 执行失败: {exc!r}", retryable=True
        ) from exc

    final_status = result.get("final_status") or "SUCCEEDED"
    if final_status == "CANCELED":
        return None
    if final_status == "WAITING":
        # 用户确认后由审批 API 重新创建同一 answer 的 GENERATE_ANSWER 任务；
        # run_agent 会基于 answer_id 复用 checkpoint，不重置计划和计数器。
        return None
    if final_status == "FAILED":
        code = result.get("error_code") or "AGENT_FAILED"
        retryable = code in _AGENT_RETRYABLE_CODES
        if settings.agent_log_payloads:
            logger.error(
                "agent_answer_failed",
                extra={
                    "answer_id": str(answer_id),
                    "error_code": code,
                    "error_summary": (result.get("error_summary") or "回答处理失败")[:200],
                    "question": question,
                },
            )
        raise PipelineError(
            "AGENT", code, (result.get("error_summary") or "回答处理失败")[:500], retryable=retryable
        )
    logger.info(
        "agent_answer_done",
        extra={
            "answer_id": str(answer_id),
            "operation": result.get("operation"),
            "answer_type": result.get("answer_type"),
            "answer": (result.get("answer_summary") or "") if settings.agent_log_payloads else None,
            "question": question if settings.agent_log_payloads else None,
        },
    )
    return None


def _run_generate_answer(
    session: Session,
    answer: Answer,
    *,
    search=None,
    retrieval_service: RetrievalService | None = None,
    chat_fn=None,
    settings: Settings | None = None,
) -> str | None:
    """GENERATE_ANSWER 主体（在独立短会话内执行，外部 HTTP 不持有 DB 事务）。"""
    settings = settings or get_settings()
    conversation = session.get(Conversation, answer.conversation_id)
    if conversation is None:
        raise PipelineError("NOT_FOUND", "CONVERSATION_NOT_FOUND", "会话不存在", retryable=False)
    message = session.get(Message, answer.message_id)
    question = message.content if message is not None else answer.summary or ""

    if answer.cancel_requested or answer.status == "CANCELED":
        _mark_canceled(session, answer)
        return None

    answer.status = "RETRIEVING"
    answer.progress_stage = "UNDERSTANDING"
    session.commit()

    flags: list[str] = []
    model_key: str | None = None
    chat = chat_fn

    # ---- 查询理解（QA 模型；失败降级原问题） ----
    normalized = question
    if settings.feature_real_qa and chat is None:
        # 注入 chat_fn（测试）时跳过模型解析；生产 chat_fn 为空才解析 QA 模型并记录 model_key
        try:
            resolved = resolve_service_model(session, "QA")
            model_key = resolved.model_config_id
            gateway = create_gateway(resolved)
            chat = lambda msgs: chat_with_retry(gateway, resolved.model_name, msgs)  # noqa: E731
        except (LLMConfigError, GatewayError) as exc:
            _fail_answer(session, answer, exc.code, f"QA 模型不可用: {exc.message}")
            raise PipelineError("CONFIG", exc.code, exc.message, retryable=False) from exc

    if settings.feature_real_qa and chat is not None:
        try:
            understanding = understand_query(
                session,
                question=question,
                filters_text=_filters_text(session, conversation.filters_snapshot),
                context_lines=_context_lines(session, conversation.id, answer.message_id),
                chat_fn=chat,
            )
        except (QaError, LLMConfigError, GatewayError) as exc:
            flags.append("QUERY_REWRITE_FAILED")
            understanding = None
    else:
        understanding = local_query_understanding(question)

    if understanding is not None and understanding.clarification_needed:
        _persist_answer(
            session, answer,
            GeneratedAnswer(
                answer_type="CLARIFICATION",
                summary=understanding.clarification_question or "请补充必要信息后重试。",
                blocks=[],
            ),
            citations_data=[],
            flags=flags,
            model_key=model_key,
            retrieval_config_revision=None,
        )
        return None

    normalized = understanding.standalone_query if (understanding and understanding.standalone_query) else question

    operation = understanding.operation if understanding is not None else "ANSWER"
    if operation == "CLARIFY":
        _persist_answer(
            session, answer,
            GeneratedAnswer(
                answer_type="CLARIFICATION",
                summary=understanding.clarification_question or "请补充必要信息后重试。",
                blocks=[],
            ),
            citations_data=[],
            flags=flags,
            model_key=model_key,
            retrieval_config_revision=None,
        )
        return None

    # ---- 非知识库请求：不触发 Embedding、BM25、向量检索或 Rerank ----
    if not _requires_retrieval(understanding, conversation):
        answer = session.get(Answer, answer.id)
        if answer is None or answer.cancel_requested or answer.status == "CANCELED":
            if answer is not None:
                _mark_canceled(session, answer)
            return None
        answer.status = "STREAMING"
        answer.progress_stage = "GENERATING"
        answer.degradation_flags = list(dict.fromkeys(flags + ["NO_KNOWLEDGE_RETRIEVAL"]))
        session.commit()
        answer = session.get(Answer, answer.id)
        try:
            if settings.feature_real_qa and chat is not None:
                generated = generate_general_answer(
                    session,
                    question=normalized,
                    operation=operation,
                    context_lines=_context_lines(session, conversation.id, answer.message_id),
                    chat_fn=chat,
                )
            else:
                generated = mock_general_answer(normalized, operation)
        except (QaError, GatewayError, LLMConfigError) as exc:
            _fail_answer(session, answer, exc.code, f"答案生成失败: {exc.message}")
            raise PipelineError(
                getattr(exc, "category", "PROVIDER"), exc.code, exc.message,
                retryable=getattr(exc, "retryable", False),
            ) from exc
        _persist_answer(
            session, answer, generated, citations_data=[], flags=flags + ["NO_KNOWLEDGE_RETRIEVAL"],
            model_key=model_key, retrieval_config_revision=None,
        )
        return None

    # ---- 检索（Phase 5） ----
    svc = retrieval_service or build_retrieval_service(search=search)
    try:
        retrieval = svc.retrieve(
            session, normalized, filters=_retrieval_filters_from_snapshot(conversation.filters_snapshot),
            operation=operation,
        )
    except RetrievalError as exc:
        _fail_answer(session, answer, exc.code, f"检索失败: {exc.message}")
        raise PipelineError(exc.category, exc.code, exc.message, retryable=exc.retryable) from exc
    # retrieve 内部已提交；重新加载会话与答案
    answer = session.get(Answer, answer.id)
    conversation = session.get(Conversation, conversation.id)
    if answer is None or answer.cancel_requested or answer.status == "CANCELED":
        if answer is not None:
            _mark_canceled(session, answer)
        return None

    answer.status = "STREAMING"
    answer.progress_stage = "GENERATING"
    answer.retrieval_run_id = retrieval.run_id
    answer.degradation_flags = list(dict.fromkeys(flags + retrieval.degradation_flags))
    session.commit()
    answer = session.get(Answer, answer.id)

    # ---- 生成 ----
    try:
        if not retrieval.evidence:
            generated = GeneratedAnswer(
                answer_type="INSUFFICIENT",
                summary="当前知识库中没有找到足以回答该问题的资料，建议调整筛选条件或换个问法。",
                blocks=[],
            )
        elif settings.feature_real_qa and chat is not None:
            evidence_text = "\n".join(
                f"[{ev.evidence_id}] {ev.title}\n{ev.content}" for ev in retrieval.evidence
            )
            generated = generate_answer(
                session,
                question=normalized,
                evidence_text=evidence_text,
                context_lines=_context_lines(session, conversation.id, answer.message_id),
                chat_fn=chat,
            )
            validate_generated(generated, [ev.evidence_id for ev in retrieval.evidence])
        else:
            generated = mock_generated_answer(normalized, retrieval.evidence)
    except (QaError, GatewayError, LLMConfigError) as exc:
        _fail_answer(session, answer, exc.code, f"答案生成失败: {exc.message}")
        raise PipelineError(
            getattr(exc, "category", "PROVIDER"), exc.code, exc.message,
            retryable=getattr(exc, "retryable", False),
        ) from exc

    # ---- 引用快照（只保留生成结果实际使用的证据） ----
    used_evidence_ids = {
        citation_id
        for block in generated.blocks
        for citation_id in block.citation_ids
    }
    cited_evidence = [
        evidence for evidence in retrieval.evidence
        if evidence.evidence_id in used_evidence_ids
    ]
    citation_id_to_no = {
        evidence.evidence_id: citation_no
        for citation_no, evidence in enumerate(cited_evidence, start=1)
    }
    citations = _build_citations(session, answer.id, cited_evidence)

    _persist_answer(
        session, answer,
        generated,
        citations_data=citations,
        citation_id_to_no=citation_id_to_no,
        flags=flags + retrieval.degradation_flags,
        model_key=model_key,
        retrieval_config_revision=retrieval.config_revision,
    )
    logger.info(
        "answer_done",
        extra={
            "answer_id": str(answer.id),
            "answer_type": generated.answer_type,
            "evidence_count": len(retrieval.evidence),
            "citation_count": len(cited_evidence),
            "flags": flags + retrieval.degradation_flags,
        },
    )
    return None


def _mark_canceled(db: Session, answer: Answer) -> None:
    if answer.status in _OPEN_STATUSES or answer.status == "PENDING":
        answer.status = "CANCELED"
        answer.progress_stage = None
        answer.completed_at = _now()
        db.commit()


def _fail_answer(db: Session, answer: Answer, code: str, message: str) -> None:
    answer.status = "FAILED"
    answer.progress_stage = None
    answer.error_code = code
    answer.error_summary = message[:500]
    answer.completed_at = _now()
    db.commit()


def _build_citations(db: Session, answer_id, evidence) -> list[dict]:
    """把证据转引用快照（DD-10 §6）：来源/版本/标题/章节/locator/摘录/原文链接/更新时间。"""
    version_ids = [ev.document_version_id for ev in evidence if ev.document_version_id]
    source_ids = [ev.source_id for ev in evidence if ev.source_id]

    doc_type_by_version: dict[uuid.UUID, str] = {}
    version_label_by_version: dict[uuid.UUID, str] = {}
    if version_ids:
        meta_rows = db.execute(
            select(DocumentMetadata, DocumentType)
            .join(DocumentType, DocumentType.id == DocumentMetadata.document_type_id)
            .where(DocumentMetadata.version_id.in_(version_ids))
        ).all()
        for meta, doc_type in meta_rows:
            doc_type_by_version[meta.version_id] = doc_type.code
        pv_rows = db.execute(
            select(DocumentMetadata.version_id, ProductVersion.version_code)
            .join(ProductVersion, ProductVersion.id == DocumentMetadata.product_version_id)
            .where(DocumentMetadata.version_id.in_(version_ids))
        ).all()
        for version_id, code in pv_rows:
            version_label_by_version[version_id] = code

    url_by_source: dict[uuid.UUID, str] = {}
    if source_ids:
        url_rows = db.execute(
            select(FeishuSourceDetail.source_id, FeishuSourceDetail.original_url).where(
                FeishuSourceDetail.source_id.in_(source_ids)
            )
        ).all()
        url_by_source = {source_id: url for source_id, url in url_rows if url}

    rows: list[dict] = []
    for no, ev in enumerate(evidence, start=1):
        excerpt = ev.content
        if len(excerpt) > 500:
            excerpt = excerpt[:500] + "…"
        rows.append(
            {
                "answer_id": answer_id,
                "citation_no": no,
                "source_id": ev.source_id,
                "version_id": ev.document_version_id,
                "chunk_id": ev.chunk_id,
                "document_title": ev.title,
                "document_type_code": doc_type_by_version.get(ev.document_version_id),
                "version_label": version_label_by_version.get(ev.document_version_id),
                "heading_path": list(ev.heading_path),
                "locator_json": ev.locator,
                "excerpt": excerpt,
                "original_url": url_by_source.get(ev.source_id),
                "source_updated_at": ev.source_updated_at,
            }
        )
    return rows


def _persist_answer(
    db: Session,
    answer: Answer,
    generated: GeneratedAnswer,
    *,
    citations_data: list[dict],
    flags: list[str],
    model_key: str | None,
    retrieval_config_revision,
    citation_id_to_no: dict[str, int] | None = None,
) -> None:
    """单一事务：Answer 最终内容 + 引用快照原子提交（DD-10 §3）。

    检索证据编号可能不连续（例如模型仅使用 E1/E4），持久化前会压缩为连续的
    citation_no，并通过 citation_id_to_no 回写各答案块。
    """
    blocks = []
    for i, block in enumerate(generated.blocks, start=1):
        citation_nos: list[int] = []
        for cid in block.citation_ids:
            no = (citation_id_to_no or {}).get(cid)
            if no is not None:
                citation_nos.append(no)
        blocks.append(
            {
                "block_id": f"b{i}",
                "type": block.type,
                "content": block.content,
                "citation_nos": citation_nos,
            }
        )
    answer.status = "SUCCEEDED"
    answer.progress_stage = None
    answer.answer_type = generated.answer_type
    answer.summary = generated.summary
    answer.blocks_json = blocks
    answer.degradation_flags = list(dict.fromkeys(flags))
    answer.retrieval_config_revision = retrieval_config_revision
    answer.model_key = model_key
    answer.error_code = None
    answer.error_summary = None
    answer.completed_at = _now()
    for citation in citations_data:
        db.add(AnswerCitation(**citation))
    db.commit()
