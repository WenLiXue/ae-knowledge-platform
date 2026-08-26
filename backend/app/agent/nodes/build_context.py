"""build_context：从数据库加载滚动记忆与最近完整问答轮次；按 token 预算选择上下文。"""

from __future__ import annotations

from ..memory import compute_context_budget, load_memory, select_recent_turns


def core_build_context(state: dict, ctx):
    with ctx.session_factory() as db:
        memory = load_memory(db, state["conversation_id"])
        budget = compute_context_budget(ctx, state.get("question") or "")
        entity_values = [e.get("value") for e in (memory.entities if memory else [])]
        turns, used = select_recent_turns(
            ctx,
            db,
            conversation_id=state["conversation_id"],
            exclude_message_id=state.get("current_message_id") or state["answer_id"],
            budget=budget["recent"],
            entity_values=entity_values,
        )

    summary = (memory.summary if memory else "") or ""
    entities = list(memory.entities) if memory else []
    constraints = list(memory.constraints) if memory else []
    unresolved = list(memory.unresolved_topics) if memory else []

    question_tokens = ctx.tokenizer.estimate(state.get("question") or "")
    summary_tokens = ctx.tokenizer.estimate(summary)
    context_estimate = (
        question_tokens
        + used
        + summary_tokens
        + ctx.tokenizer.estimate_list([str(e) for e in entities])
        + ctx.tokenizer.estimate_list(constraints)
    )
    return {
        "recent_turns": turns,
        "memory_summary": summary,
        "memory_entities": entities,
        "memory_constraints": constraints,
        "unresolved_topics": unresolved,
        "context_token_estimate": context_estimate,
    }
