"""问答领域契约（DD-07 §5.3、§12.1）。

- QueryUnderstanding：查询理解输出（独立问题、实体、澄清标志）；
- GeneratedAnswer：生成答案的可组合结构（blocks + evidence 引用），
  citation_ids 指向证据集合中的 evidence_id（E1..En），由 Worker 映射为引用编号。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DetectedEntity(BaseModel):
    entity_type: str
    value: str


class QueryUnderstanding(BaseModel):
    # 主 Agent 的内部业务意图。CHAT/EXPLAIN 可在不依赖知识库的情况下回答；
    # ANSWER/SUMMARIZE/RELATE 必须经过检索，避免把所有输入都当成 RAG 问题。
    operation: Literal["ANSWER", "SUMMARIZE", "RELATE", "EXPLAIN", "CHAT", "CLARIFY"] = "ANSWER"
    standalone_query: str
    detected_entities: list[DetectedEntity] = Field(default_factory=list)
    intent_hint: str | None = None
    clarification_needed: bool = False
    clarification_question: str | None = None
    reason_code: str | None = None


class GeneratedBlock(BaseModel):
    type: Literal["paragraph", "table", "list", "scope", "warning", "conflict"]
    content: dict | str
    citation_ids: list[str] = Field(default_factory=list)


class GeneratedAnswer(BaseModel):
    answer_type: Literal[
        "ANSWER", "PARTIAL", "CLARIFICATION", "INSUFFICIENT", "CONFLICT_WARNING"
    ]
    summary: str
    blocks: list[GeneratedBlock] = Field(default_factory=list)
    follow_up_suggestions: list[str] = Field(default_factory=list)
