"""分类服务：编排短事务、模型调用与结果应用（DD-19 §8.5）。

事务边界：
1. 短事务读取版本、配置与已存在 input_hash；
2. 提交释放锁，事务外构造输入并调用模型（一次修复）；
3. 短事务锁定版本，校验未下线/未被替代；
4. 插入 ClassificationResult；
5. 领域服务应用 metadata / 状态；
6. 创建下一阶段任务（由流水线在返回后统一完成）。

模型不可用禁止默认相关；重复任务优先复用已验证结果（input_hash 幂等）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models.knowledge import DocumentVersion, KnowledgeSource
from ..db.models.rag import ClassificationResult, DocumentMetadata
from ..model_gateway.base import ChatRequest, ChatResponse
from ..model_gateway.errors import GatewayError
from ..parsing.schemas import ParsedDocument
from .config import ClassificationConfig, load_classification_config
from .input_builder import build_input_blocks, compute_input_hash
from .prompts import build_messages, build_repair_messages
from .schemas import ClassificationOutput
from .validator import as_issue_dict, validate_output

RELEVANT = "RELEVANT"
IRRELEVANT = "IRRELEVANT"
UNCERTAIN = "UNCERTAIN"


class ClassificationError(Exception):
    """分类领域错误。category/code 稳定，retryable 决定任务是否重试。"""

    def __init__(self, category: str, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.category = category
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class ClassificationRunResult:
    """一次分类运行的程序结论与流水线衔接。"""

    decision: str
    classification_result_id: uuid.UUID | None = None
    reused: bool = False
    next_stage: str | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _chat(gateway, model_name: str, messages: list[dict]) -> tuple[str, dict]:
    """调用网关并返回 (content, usage_dict)。网关错误原样向上抛。"""
    response: ChatResponse = gateway.chat(
        ChatRequest(model=model_name, messages=messages, temperature=0)
    )
    usage = response.usage
    return response.content, {
        "prompt_tokens": usage.prompt_tokens if usage else 0,
        "completion_tokens": usage.completion_tokens if usage else 0,
        "total_tokens": usage.total_tokens if usage else 0,
    }


def _call_and_validate(
    *,
    gateway,
    resolved,
    config: ClassificationConfig,
    source_title: str,
    source_type: str,
    blocks,
) -> tuple[ClassificationOutput, str, dict]:
    """事务外：构造输入 → 调模型 → 校验，首次失败一次修复。"""
    messages = build_messages(
        source_title=source_title,
        source_type=source_type,
        filename=None,
        taxonomy=config.taxonomy,
        blocks=blocks,
        relevance_policy=config.relevance_policy,
    )
    first_raw, usage = _chat(gateway, resolved.model_name, messages)
    first = validate_output(first_raw, blocks=blocks, taxonomy=config.taxonomy, config=config)
    if first.valid:
        assert first.output is not None and first.decision is not None
        return first.output, first.decision, usage

    # 一次结构化修复调用（DD-19 §8.4）
    repair_messages = build_repair_messages(
        messages, first_raw, [as_issue_dict(issue) for issue in first.issues]
    )
    second_raw, second_usage = _chat(gateway, resolved.model_name, repair_messages)
    second = validate_output(second_raw, blocks=blocks, taxonomy=config.taxonomy, config=config)
    if second.valid:
        assert second.output is not None and second.decision is not None
        return second.output, second.decision, second_usage
    raise ClassificationError(
        "VALIDATION",
        "CLASSIFY_OUTPUT_INVALID",
        "分类输出校验失败（含一次修复），进入任务重试",
        retryable=True,
    )


def _find_existing(session: Session, version_id: uuid.UUID, input_hash: str) -> ClassificationResult | None:
    return session.execute(
        select(ClassificationResult)
        .where(
            ClassificationResult.version_id == version_id,
            ClassificationResult.input_hash == input_hash,
            ClassificationResult.status == "VALID",
        )
        .order_by(ClassificationResult.created_at.desc())
    ).scalars().first()


def _resolve_code(taxonomy: dict, category: str, code: str | None) -> uuid.UUID | None:
    if not code:
        return None
    for item in taxonomy.get(category) or []:
        if item.get("code") == code:
            return uuid.UUID(str(item["id"]))
    return None


def _field_sources(output: ClassificationOutput, overridden: set[str] | None = None) -> dict:
    """逐字段来源：默认 MODEL，人工覆盖字段标记 MANUAL。"""
    overridden = overridden or set()
    fields = (
        "product_code",
        "product_version_code",
        "document_type_code",
        "product_form_code",
        "is_domestic",
        "module_name",
        "business_topic",
        "summary",
        "keywords",
    )
    return {field: ("MANUAL" if field in overridden else "MODEL") for field in fields}


def _upsert_metadata(
    session: Session,
    *,
    version_id: uuid.UUID,
    result_id: uuid.UUID,
    output: ClassificationOutput,
    taxonomy: dict,
    overridden: set[str] | None = None,
) -> DocumentMetadata:
    meta = session.get(DocumentMetadata, version_id)
    if meta is None:
        meta = DocumentMetadata(version_id=version_id)
        session.add(meta)
    meta.classification_result_id = result_id
    meta.product_id = _resolve_code(taxonomy, "products", output.product_code)
    meta.product_version_id = _resolve_code(taxonomy, "product_versions", output.product_version_code)
    meta.document_type_id = _resolve_code(taxonomy, "document_types", output.document_type_code)
    meta.product_form_id = _resolve_code(taxonomy, "product_forms", output.product_form_code)
    meta.is_domestic = output.is_domestic
    meta.module_name = output.module_name
    meta.business_topic = output.business_topic
    meta.summary = output.summary
    meta.keywords = output.keywords
    meta.field_sources = _field_sources(output, overridden)
    meta.field_confidence = output.field_confidence
    session.flush()
    return meta


def _apply_decision(
    session: Session,
    *,
    version: DocumentVersion,
    source: KnowledgeSource,
    result: ClassificationResult,
    output: ClassificationOutput,
    decision: str,
    taxonomy: dict,
    overridden: set[str] | None = None,
) -> str | None:
    """领域服务应用 metadata 与状态，返回下一阶段；None 表示流水线终止。"""
    version.classification_config_revision = result.classification_config_revision
    if decision == RELEVANT:
        _upsert_metadata(
            session, version_id=version.id, result_id=result.id,
            output=output, taxonomy=taxonomy, overridden=overridden,
        )
        version.processing_stage = None
        return "CHUNK"
    if decision == UNCERTAIN:
        version.status = "PENDING_CONFIRMATION"
        version.processing_stage = None
        source.status = "PENDING_CONFIRMATION"
        return None
    # IRRELEVANT
    version.status = "FAILED"
    version.error_code = "CLASSIFIED_IRRELEVANT"
    version.error_summary = "分类判定与平台知识无关，不入库"
    version.processing_stage = None
    source.status = "OFFLINE"
    source.offline_reason = output.reason_summary or "明确无关"
    source.offlined_at = _now()
    return None


def _reuse_output(result: ClassificationResult) -> tuple[ClassificationOutput, str]:
    """从已验证结果还原输出与决策（防御：存储值异常时降级为 UNCERTAIN）。"""
    if result.output_json:
        try:
            output = ClassificationOutput.model_validate(result.output_json)
            decision = result.relevance or UNCERTAIN
            return output, decision
        except Exception:  # noqa: BLE001
            pass
    return ClassificationOutput(relevance="UNCERTAIN", relevance_confidence=0.0, reason_summary="结果回放失败"), UNCERTAIN


def run_classification(
    outer_session: Session,
    *,
    version_id: uuid.UUID,
    source_id: uuid.UUID,
    parsed: ParsedDocument,
    gateway,
    resolved,
    config: ClassificationConfig | None = None,
) -> ClassificationRunResult:
    """执行一次分类运行（§8.5 事务边界）。

    使用独立短会话 `work`：短事务读取版本/配置/input_hash 后提交释放读锁，
    事务外调用模型（一次修复），再短事务锁定版本插入结果并应用状态。
    模型 HTTP 调用不持有任何数据库事务或业务行锁；外层任务事务只负责任务状态。
    """
    from sqlalchemy.orm import Session as _Session

    work = _Session(bind=outer_session.get_bind())
    try:
        version = work.get(DocumentVersion, version_id)
        source = work.get(KnowledgeSource, source_id)
        if version is None or source is None:
            raise ClassificationError(
                "NOT_FOUND", "VERSION_MISSING", "分类目标版本或来源不存在", retryable=False
            )

        active_config = config or load_classification_config(work)
        input_hash = compute_input_hash(
            content_sha256=version.content_sha256,
            config_revision=active_config.config_revision,
            model_key=resolved.model_config_id,
            model_revision=resolved.config_revision,
            prompt_revision=active_config.prompt_revision,
            input_builder_revision=active_config.input_builder_revision,
        )

        existing = _find_existing(work, version_id, input_hash)
        # 短事务①：读取完成后提交，释放读锁；模型调用不得持有 DB 事务（§8.5）
        work.commit()

        if existing is not None:
            output, decision = _reuse_output(existing)
            reused = True
            result_row = existing
        else:
            blocks, _stats = build_input_blocks(parsed, active_config.taxonomy, active_config.budget)
            if not blocks:
                raise ClassificationError(
                    "VALIDATION", "CLASSIFY_EMPTY_INPUT", "受控输入为空，无法分类", retryable=False
                )
            output, decision, usage = _call_and_validate(
                gateway=gateway,
                resolved=resolved,
                config=active_config,
                source_title=parsed.title,
                source_type=parsed.source_type,
                blocks=blocks,
            )
            reused = False
            result_row = None

        # 短事务②：锁定版本，校验未下线/未被替代（§8.5.3）
        version = work.execute(
            select(DocumentVersion).where(DocumentVersion.id == version_id).with_for_update()
        ).scalar_one_or_none()
        source = work.get(KnowledgeSource, source_id)
        if version is None or source is None:
            return ClassificationRunResult(decision, None, reused, None)
        if source.status == "OFFLINE" or version.status not in ("PROCESSING", "PENDING_CONFIRMATION"):
            # 文档已被替代/下线：取消应用结果，任务安全结束（DD-05 §13）
            return ClassificationRunResult(decision, None, reused, None)

        if result_row is None:
            result_row = ClassificationResult(
                version_id=version_id,
                status="VALID",
                relevance=decision,
                relevance_confidence=output.relevance_confidence,
                output_json=output.model_dump(),
                evidence_json=[e.model_dump() for e in output.evidence],
                missing_fields=output.missing_fields,
                reason_summary=output.reason_summary,
                model_key=resolved.model_config_id,
                model_revision=str(resolved.config_revision) if resolved.config_revision is not None else None,
                prompt_revision=active_config.prompt_revision,
                input_builder_revision=active_config.input_builder_revision,
                classification_config_revision=active_config.config_revision,
                input_hash=input_hash,
                token_usage_json=usage,
            )
            work.add(result_row)
            work.flush()

        next_stage = _apply_decision(
            work,
            version=version,
            source=source,
            result=result_row,
            output=output,
            decision=decision,
            taxonomy=active_config.taxonomy,
        )
        work.commit()
        return ClassificationRunResult(
            decision=decision,
            classification_result_id=result_row.id,
            reused=reused,
            next_stage=next_stage,
        )
    finally:
        work.close()
