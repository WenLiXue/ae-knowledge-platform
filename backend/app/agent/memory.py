"""会话记忆与 token 预算（DD-21 §8）。

- MemorySnapshot：conversation_memories 的一行快照（摘要/实体/约束/待解决主题）；
- compute_context_budget：按模型窗口动态分配 recent/summary/evidence 预算；
- select_recent_turns：按 token 预算选择最近完整问答轮次（保留完整轮次、
  指代相关实体轮次优先）；
- compact_prompt / update_memory：滚动摘要（乐观锁 revision，冲突重读合并一次）。

原始消息永不因摘要而删除；本模块只推进 last_message_id 水位。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models.conversation import Answer, ConversationMemory, Message
from .context import AgentRuntimeContext

_COMPACTION_MAX_NEW_MESSAGES = 12


@dataclass(frozen=True)
class MemorySnapshot:
    summary: str = ""
    entities: list[dict] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    unresolved_topics: list[str] = field(default_factory=list)
    last_message_id: uuid.UUID | None = None
    token_estimate: int = 0
    revision: int = 1


def load_memory(db: Session, conversation_id) -> MemorySnapshot | None:
    row = db.get(ConversationMemory, uuid.UUID(str(conversation_id)))
    if row is None:
        return None
    return MemorySnapshot(
        summary=row.summary or "",
        entities=list(row.entities or []),
        constraints=list(row.constraints or []),
        unresolved_topics=list(row.unresolved_topics or []),
        last_message_id=row.last_message_id,
        token_estimate=row.token_estimate or 0,
        revision=row.revision,
    )


def compute_context_budget(ctx: AgentRuntimeContext, question: str) -> dict:
    """按模型窗口 + 系统提示 + 输出预留动态分配（DD-21 §8.3）。

    返回 {"recent": int, "summary": int, "evidence": int, "available": int}。
    """
    settings = ctx.settings
    window = settings.agent_default_context_window
    # 系统提示 + 指令的保守估算
    system_tokens = ctx.tokenizer.estimate(
        "你是企业知识助手。只依据证据回答。引用必须来自证据。意图为受控枚举。"
        "禁止编造内部产品事实。"
    )
    reserved = settings.agent_reserved_output_tokens
    safety = int(window * 0.05)
    available = max(1000, window - system_tokens - reserved - safety)

    recent = min(settings.conversation_recent_token_budget, int(available * 0.20))
    summary = min(settings.conversation_summary_token_budget, int(available * 0.10))
    question_tokens = ctx.tokenizer.estimate(question or "")
    evidence = max(
        0,
        available - recent - summary - question_tokens
        - ctx.tokenizer.estimate_list(["约束:", "实体:", "待解决:"]),
    )
    return {"recent": recent, "summary": summary, "evidence": evidence, "available": available}


def _load_turns(db: Session, conversation_id, exclude_message_id) -> list[dict]:
    """从当前问题倒序加载完整问答轮次（user 消息 + 其 SUCCEEDED 答案摘要）。"""
    messages = list(
        db.execute(
            select(Message)
            .where(Message.conversation_id == uuid.UUID(str(conversation_id)))
            .order_by(Message.created_at.desc(), Message.id.desc())
        ).scalars()
    )
    answers = {
        a.message_id: a
        for a in db.execute(
            select(Answer).where(Answer.conversation_id == uuid.UUID(str(conversation_id)))
        ).scalars()
    }
    turns: list[dict] = []
    for message in messages:
        if message.id == uuid.UUID(str(exclude_message_id)):
            continue  # 当前问题单独携带
        answer = answers.get(message.id)
        assistant = None
        if answer is not None and answer.status == "SUCCEEDED" and answer.summary:
            assistant = answer.summary
        turns.append(
            {
                "user": message.content,
                "assistant": assistant,
                "message_id": str(message.id),
                "answer_id": str(answer.id) if answer else None,
                "created_at": message.created_at.isoformat() if message.created_at else None,
            }
        )
    return turns  # newest first


def _turn_tokens(ctx: AgentRuntimeContext, turn: dict) -> int:
    return ctx.tokenizer.estimate(turn.get("user") or "") + ctx.tokenizer.estimate(
        turn.get("assistant") or ""
    )


def select_recent_turns(
    ctx: AgentRuntimeContext,
    db: Session,
    *,
    conversation_id,
    exclude_message_id,
    budget: int,
    entity_values: list[str],
) -> tuple[list[dict], int]:
    """按 token 预算选择最近完整轮次（DD-21 §8.4）。

    - 最新一轮必选（保留完整问题+答案，不截半轮）；
    - 包含指代实体的轮次优先；
    - 超预算的旧轮次进入滚动摘要（此处不删除消息）。
    返回（按时间升序的轮次列表, 估算 token 数）。
    """
    turns = _load_turns(db, conversation_id, exclude_message_id)  # newest first
    entity_values = [v for v in (entity_values or []) if v]

    def relevant(turn: dict) -> bool:
        if not entity_values:
            return False
        text = f"{turn.get('user') or ''} {turn.get('assistant') or ''}"
        return any(v and v in text for v in entity_values)

    selected: list[dict] = []
    used = 0

    def try_add(turn: dict) -> bool:
        nonlocal used
        cost = _turn_tokens(ctx, turn)
        if used + cost > budget:
            return False
        selected.append(turn)
        used += cost
        return True

    if turns and not try_add(turns[0]):
        # 最新一轮超预算：仍保留问题（截断答案），确保不丢问题
        turn = dict(turns[0])
        turn["assistant"] = (turn.get("assistant") or "")[:200] or None
        selected.append(turn)
        used += _turn_tokens(ctx, turn)

    rest = turns[1:]
    for turn in rest:  # 实体相关轮次优先
        if relevant(turn):
            if not try_add(turn):
                break
    for turn in rest:  # 再按新近度填充
        if turn not in selected:
            if not try_add(turn):
                break

    selected.sort(key=lambda t: (t.get("created_at") or ""))
    return selected, used


def should_compact(db: Session, memory: MemorySnapshot | None, conversation_id, *, ctx) -> bool:
    """压缩触发条件（DD-21 §8.5）：未摘要新消息超预算比例或条数超阈值。"""
    settings = ctx.settings
    after_id = memory.last_message_id if memory else None
    query = select(Message).where(Message.conversation_id == uuid.UUID(str(conversation_id)))
    if after_id is not None:
        anchor = db.get(Message, after_id)
        if anchor is not None:
            query = query.where(Message.created_at > anchor.created_at)
    rows = list(db.execute(query.order_by(Message.created_at)).scalars())
    if not rows:
        return False
    if len(rows) > _COMPACTION_MAX_NEW_MESSAGES:
        return True
    tokens = ctx.tokenizer.estimate_list([m.content for m in rows])
    budget = settings.conversation_recent_token_budget
    return tokens > int(budget * settings.conversation_compaction_trigger_ratio)


def build_compact_messages(memory: MemorySnapshot | None, turns: list[dict]) -> list[dict]:
    """构造摘要模型输入（旧摘要 + 待压缩轮次），输出结构化 JSON。"""
    parts = ["请把以下对话压缩为结构化会话记忆，只输出一个 JSON 对象："]
    if memory and memory.summary:
        parts.append(f"旧摘要：{memory.summary}")
    if memory and memory.entities:
        parts.append(f"已确认实体：{memory.entities}")
    lines = []
    for turn in turns:
        q = turn.get("user") or ""
        a = turn.get("assistant")
        lines.append(f"问：{q}")
        if a:
            lines.append(f"答：{a[:300]}")
    parts.append("\n".join(lines))
    parts.append(
        'JSON 结构：{"summary": string, "entities": [{"entity_type": string, "value": string}], '
        '"constraints": string[], "unresolved_topics": string[]}'
    )
    return [{"role": "system", "content": "你是会话记忆摘要器。"}, {"role": "user", "content": "\n".join(parts)}]


def parse_memory_patch(content: str, tokenizer) -> dict:
    """把模型输出解析为 memory_patch。结构非法抛 ValueError（调用方修复一次）。"""
    import json

    text = content.strip()
    if text.startswith("```"):
        text = "\n".join(text.splitlines()[1:])
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3].rstrip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("记忆摘要输出不是合法 JSON")
    data = json.loads(text[start : end + 1])
    patch = {
        "summary": str(data.get("summary") or ""),
        "entities": list(data.get("entities") or []),
        "constraints": [str(c) for c in (data.get("constraints") or [])],
        "unresolved_topics": [str(t) for t in (data.get("unresolved_topics") or [])],
    }
    for key, value in patch.items():
        if key == "entities":
            continue
        if tokenizer.estimate(str(value)) > 1500:
            raise ValueError("记忆摘要超出预算")
    return patch


def update_memory(
    db: Session,
    conversation_id,
    *,
    patch: dict,
    advance_message_id,
    token_estimate: int = 0,
) -> bool:
    """乐观锁更新 ConversationMemory；冲突时重读合并一次。失败返回 False（降级）。

    不删除任何消息；advance_message_id 为已压缩到的水位。
    """
    conversation_id = uuid.UUID(str(conversation_id))
    row = db.get(ConversationMemory, conversation_id)
    if row is None:
        row = ConversationMemory(
            conversation_id=conversation_id,
            summary=patch.get("summary") or "",
            entities=patch.get("entities") or [],
            constraints=patch.get("constraints") or [],
            unresolved_topics=patch.get("unresolved_topics") or [],
            last_message_id=advance_message_id,
            token_estimate=token_estimate,
            revision=1,
        )
        db.add(row)
        db.commit()
        return True

    expected = row.revision
    merged = _merge_patch(row, patch)
    row.summary = merged["summary"]
    row.entities = merged["entities"]
    row.constraints = merged["constraints"]
    row.unresolved_topics = merged["unresolved_topics"]
    if advance_message_id is not None:
        row.last_message_id = advance_message_id
    row.token_estimate = token_estimate
    row.revision = expected + 1

    result = db.execute(
        select(ConversationMemory).where(
            ConversationMemory.conversation_id == conversation_id,
            ConversationMemory.revision == expected,
        ).with_for_update()
    ).scalars().first()
    if result is None:
        # 冲突：重读合并一次
        db.rollback()
        row2 = db.get(ConversationMemory, conversation_id)
        if row2 is None:
            return False
        merged2 = _merge_patch(row2, patch)
        row2.summary = merged2["summary"]
        row2.entities = merged2["entities"]
        row2.constraints = merged2["constraints"]
        row2.unresolved_topics = merged2["unresolved_topics"]
        if advance_message_id is not None:
            row2.last_message_id = advance_message_id
        row2.token_estimate = token_estimate
        row2.revision += 1
        db.commit()
        return True
    db.commit()
    return True


def _merge_patch(row, patch: dict) -> dict:
    return {
        "summary": patch.get("summary") or row.summary or "",
        "entities": _merge_unique(list(row.entities or []), list(patch.get("entities") or []), key="value"),
        "constraints": _merge_unique_str(list(row.constraints or []), list(patch.get("constraints") or [])),
        "unresolved_topics": _merge_unique_str(
            list(row.unresolved_topics or []), list(patch.get("unresolved_topics") or [])
        ),
    }


def _merge_unique_str(existing: list[str], incoming: list[str]) -> list[str]:
    seen = set(existing)
    merged = list(existing)
    for item in incoming:
        if item and item not in seen:
            seen.add(item)
            merged.append(item)
    return merged


def _merge_unique(existing: list[dict], incoming: list[dict], *, key: str) -> list[dict]:
    seen = {str(e.get(key)) for e in existing if e.get(key)}
    merged = list(existing)
    for item in incoming:
        k = item.get(key)
        if k and k not in seen:
            seen.add(k)
            merged.append(item)
    return merged
