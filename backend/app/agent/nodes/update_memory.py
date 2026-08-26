"""update_memory：更新摘要/实体/用户约束/待解决主题；失败时 MEMORY_UPDATE_FAILED，不影响已验证答案。"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select

from ...db.models.conversation import Answer, Message
from ..memory import (
    build_compact_messages,
    load_memory,
    parse_memory_patch,
    should_compact,
    update_memory as persist_memory,
)
from . import dedupe_flags

_CONSTRAINT_PATTERNS = (
    (re.compile(r"只看\s*V?(\d+(?:\.\d+)*)"), "只看版本 {0}"),
    (re.compile(r"(?:仅|只|优先)\s*(?:看|查|用)?\s*V?(\d+(?:\.\d+)*)"), "限定版本 {0}"),
    (re.compile(r"(?:用|使用|以)\s*(中文|英文)"), "使用{0}回答"),
    (re.compile(r"(?:简要|简略|精简)"), "简要回答"),
)


def _extract_constraints(question: str, existing: list[str]) -> list[str]:
    merged = list(existing or [])
    for pattern, template in _CONSTRAINT_PATTERNS:
        for match in pattern.findall(question or ""):
            label = template.format(match)
            if label not in merged:
                merged.append(label)
    return merged


def _local_patch(state: dict, memory) -> dict:
    entities = [
        {"entity_type": e.get("entity_type"), "value": e.get("value")}
        for e in (state.get("query_entities") or [])
        if e.get("value")
    ]
    constraints = _extract_constraints(
        state.get("question") or "", list(memory.constraints) if memory else []
    )
    return {
        "summary": (memory.summary if memory else "") or "",
        "entities": entities,
        "constraints": constraints,
        "unresolved_topics": list(memory.unresolved_topics) if memory else [],
    }


def _mock_compact_patch(memory, turns: list[dict]) -> dict:
    summary = (memory.summary if memory else "") or ""
    questions = [t.get("user") for t in turns if t.get("user")]
    if questions:
        new = "；".join(questions[-10:])
        summary = (summary + "\n" + new) if summary else new
    return {"summary": summary, "entities": [], "constraints": [], "unresolved_topics": []}


def _compact_patch(ctx, db, state: dict, memory) -> tuple[dict, int]:
    """压缩：调用摘要模型（修复一次）；mock 模式确定性摘要。返回 (patch, repair_count)。"""
    turns: list[dict] = []
    after_id = memory.last_message_id if memory else None
    query = select(Message).where(Message.conversation_id == uuid.UUID(str(state["conversation_id"])))
    if after_id is not None:
        anchor = db.get(Message, after_id)
        if anchor is not None:
            query = query.where(Message.created_at > anchor.created_at)
    answers = {
        a.message_id: a
        for a in db.execute(
            select(Answer).where(Answer.conversation_id == uuid.UUID(str(state["conversation_id"])))
        ).scalars()
    }
    for message in db.execute(query.order_by(Message.created_at)).scalars():
        answer = answers.get(message.id)
        turns.append(
            {
                "user": message.content,
                "assistant": answer.summary if answer and answer.status == "SUCCEEDED" else None,
            }
        )
    turns.append({"user": state.get("question") or "", "assistant": state.get("answer_summary")})

    if not ctx.settings.feature_real_qa:
        return _mock_compact_patch(memory, turns), 0

    messages = build_compact_messages(memory, turns)
    repair_count = 0
    try:
        content = ctx.models.chat(messages)
        return parse_memory_patch(content, ctx.tokenizer), repair_count
    except Exception:  # noqa: BLE001 修复一次
        repair_count = 1
        try:
            content = ctx.models.chat(
                messages + [{"role": "user", "content": "上次输出校验失败，请只输出合法 JSON。"}]
            )
            return parse_memory_patch(content, ctx.tokenizer), repair_count
        except Exception:  # noqa: BLE001 记忆更新失败 → 降级
            raise


def core_update_memory(state: dict, ctx):
    conversation_id = uuid.UUID(str(state["conversation_id"]))
    flags = list(state.get("degradation_flags") or [])
    memory_patch: dict = {}
    advance_id = None
    repaired = 0

    with ctx.session_factory() as db:
        memory = load_memory(db, conversation_id)
        if should_compact(db, memory, conversation_id, ctx=ctx):
            try:
                memory_patch, repaired = _compact_patch(ctx, db, state, memory)
                advance_id = state.get("current_message_id")
            except Exception:  # noqa: BLE001 记忆压缩失败 → 降级保留旧记忆
                flags = dedupe_flags(flags + ["MEMORY_UPDATE_FAILED"])
                memory_patch = _local_patch(state, memory)
        else:
            memory_patch = _local_patch(state, memory)

        token_estimate = ctx.tokenizer.estimate(memory_patch.get("summary") or "")
        ok = persist_memory(
            db,
            conversation_id,
            patch=memory_patch,
            advance_message_id=advance_id,
            token_estimate=token_estimate,
        )
        if not ok:
            flags = dedupe_flags(flags + ["MEMORY_UPDATE_FAILED"])

    return {
        "memory_patch": memory_patch,
        "degradation_flags": dedupe_flags(flags),
        "memory_repair_count": state.get("memory_repair_count", 0) + repaired,
    }
