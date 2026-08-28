"""Knowledge tools backed by the existing RetrievalService.

The tool owns the adapter boundary; ranking, pgvector and evidence selection
remain in the retrieval domain service.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from ...retrieval.schemas import RetrievalFilters
from ...retrieval.service import build_retrieval_service
from ..contracts.tool import ToolDefinition, ToolResultEnvelope
from .base import AgentTool, ToolContext, ToolError


class KnowledgeSearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    operation: Literal["ANSWER", "SUMMARIZE", "RELATE", "EXPLAIN"] = "ANSWER"
    product_id: uuid.UUID | None = None
    version_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    document_type_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)


class KnowledgeSearchOutput(BaseModel):
    status: Literal["SUCCEEDED", "EMPTY"]
    evidence: list[dict]
    evidence_status: str
    retrieval_run_id: str | None = None
    degradation_flags: list[str] = Field(default_factory=list)


class KnowledgeSearchTool:
    input_model = KnowledgeSearchInput
    output_model = KnowledgeSearchOutput
    definition = ToolDefinition(
        name="knowledge.search",
        version="1.0",
        description="在当前用户可见的企业知识库中检索产品、版本和配置资料。",
        input_schema=KnowledgeSearchInput.model_json_schema(),
        output_schema=KnowledgeSearchOutput.model_json_schema(),
        layer="RESOURCE",
        owner="knowledge",
        risk="READ_ONLY",
        side_effect=False,
        requires_confirmation=False,
        idempotency="NOT_APPLICABLE",
        required_permissions=["knowledge:read"],
        timeout_seconds=90,
        max_retries=1,
        sensitivity="INTERNAL",
    )

    def execute(self, args: KnowledgeSearchInput, context: ToolContext) -> ToolResultEnvelope:
        if context.session_factory is None:
            raise ToolError("TOOL_CONTEXT_INVALID", "知识工具缺少数据库会话工厂")
        factory = context.services.get("retrieval_service_factory") or build_retrieval_service
        service = factory()
        filters = RetrievalFilters(
            product_id=args.product_id,
            version_ids=args.version_ids,
            document_type_ids=args.document_type_ids,
        )
        started = datetime.now(timezone.utc)
        try:
            with context.session_factory() as db:
                result = service.retrieve(db, args.query, filters=filters, operation=args.operation)
        except Exception as exc:
            # Preserve the domain error code without exposing provider details.
            code = getattr(exc, "code", None) or "KNOWLEDGE_SEARCH_FAILED"
            raise ToolError(code, "知识库检索失败", retryable=bool(getattr(exc, "retryable", False))) from exc

        evidence = []
        refs = []
        for item in result.evidence:
            evidence_id = item.evidence_id
            ref = {
                "evidence_id": evidence_id,
                "chunk_id": str(item.chunk_id),
                "source_id": str(item.source_id),
                "document_version_id": str(item.document_version_id),
            }
            refs.append(ref)
            evidence.append(
                {
                    **ref,
                    "title": item.title,
                    "content": item.content,
                    "heading_path": item.heading_path,
                    "locator": item.locator,
                    "source_priority": item.source_priority,
                    "source_updated_at": item.source_updated_at.isoformat() if item.source_updated_at else None,
                }
            )
        output = KnowledgeSearchOutput(
            status="SUCCEEDED" if evidence else "EMPTY",
            evidence=evidence,
            evidence_status=result.evidence_status,
            retrieval_run_id=str(result.run_id) if result.run_id else None,
            degradation_flags=list(result.degradation_flags),
        )
        return ToolResultEnvelope(
            call_id=str(context.metadata.get("call_id") or uuid.uuid4()),
            tool_name=self.definition.name,
            tool_version=self.definition.version,
            status="SUCCEEDED",
            data=output.model_dump(mode="json"),
            summary=(f"检索到 {len(evidence)} 条企业证据" if evidence else "未检索到足够的企业证据"),
            evidence_refs=refs,
            retryable=False,
            sensitivity=self.definition.sensitivity,
            started_at=started,
            completed_at=datetime.now(timezone.utc),
        )


def register_knowledge_tools(registry) -> None:
    """Register read-only knowledge tools into an application-owned registry."""
    from .registry import ToolRegistry

    if not isinstance(registry, ToolRegistry):
        raise TypeError("registry must be ToolRegistry")
    if "knowledge.search" not in registry.names():
        registry.register(KnowledgeSearchTool())
