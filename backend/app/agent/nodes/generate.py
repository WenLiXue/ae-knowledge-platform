"""生成节点：generate_general / generate_grounded / finalize_clarification / finalize_insufficient。

- generate_general：普通对话/一般解释，不注入知识证据，不生成内部产品事实；
- generate_grounded：只根据本轮 evidence 回答，生成结构化引用草稿；
- finalize_*：澄清/依据不足的明确回答，不伪造事实与引用。
"""

from __future__ import annotations

import uuid
import json
import re
import time

from ...qa.llm import mock_generated_answer, mock_general_answer
from ...qa.prompts import GENERAL_GENERATION_SYSTEM_PROMPT, GENERATION_SYSTEM_PROMPT
from ...qa.schemas import GeneratedAnswer
from ...retrieval.schemas import EvidenceItem
from ..citations import build_citations, map_blocks
from . import dedupe_flags


def _turns_to_lines(turns: list[dict]) -> list[str]:
    lines: list[str] = []
    for turn in turns:
        lines.append(f"问：{turn.get('user') or ''}")
        if turn.get("assistant"):
            lines.append(f"答：{turn.get('assistant') or ''}")
    return lines


def _parse_generated(text: str) -> GeneratedAnswer:
    content = text.strip()
    if content.startswith("```"):
        content = "\n".join(content.splitlines()[1:])
        if content.rstrip().endswith("```"):
            content = content.rstrip()[:-3].rstrip()
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("生成输出不是合法 JSON")
    import json

    return GeneratedAnswer.model_validate(json.loads(content[start : end + 1]))


def _call_json(ctx, system_prompt: str, user_content: str) -> GeneratedAnswer:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    try:
        return _parse_generated(ctx.models.chat(messages))
    except Exception as first_err:  # noqa: BLE001 最多修复一次
        hint = str(first_err)[:300]
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{user_content}\n\n上次输出校验失败：{hint}\n请重新输出合法 JSON。"},
        ]
        return _parse_generated(ctx.models.chat(messages))


def _stream_json(ctx, system_prompt: str, user_content: str, answer_id: str) -> GeneratedAnswer:
    """Stream a structured answer while exposing only its readable summary.

    The provider still returns one final JSON document. During generation we
    extract the completed ``summary`` string and persist it as a draft, so SSE
    clients see useful text without rendering malformed JSON or unvalidated
    citations.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    chunks: list[str] = []
    last_write = 0.0

    def persist_draft(text: str) -> None:
        nonlocal last_write
        now = time.monotonic()
        if not text or now - last_write < 0.15:
            return
        last_write = now
        try:
            from ...db.models.conversation import Answer

            with ctx.session_factory() as db:
                answer = db.get(Answer, uuid.UUID(str(answer_id)))
                if answer is not None and answer.status not in ("CANCELED", "FAILED"):
                    answer.draft_text = text[:12000]
                    db.commit()
        except Exception:
            # Drafts are an observability/UI enhancement; never fail the
            # authoritative answer because a progress write was unavailable.
            return

    try:
        for chunk in ctx.models.stream_chat(
            messages,
            timeout_seconds=max(5.0, ctx.deadline - ctx.clock().timestamp()),
        ):
            chunks.append(chunk)
            raw = "".join(chunks)
            match = re.search(r'"summary"\s*:\s*"((?:\\.|[^"\\])*)', raw)
            if match:
                try:
                    persist_draft(json.loads('"' + match.group(1) + '"'))
                except ValueError:
                    pass
        return _parse_generated("".join(chunks))
    except (AttributeError, NotImplementedError, ValueError):
        return _parse_generated(ctx.models.chat(messages))
def _generated_update(generated: GeneratedAnswer, citation_drafts: list[dict], ctx) -> dict:
    return {
        "answer_type": generated.answer_type,
        "answer_summary": generated.summary,
        "citation_drafts": citation_drafts,
        "model_key": ctx.models.last_model_key,
        "final_status": "SUCCEEDED",
    }


def core_generate_general(state: dict, ctx):
    question = state.get("normalized_question") or state.get("question") or ""
    operation = state.get("operation") or "CHAT"
    context_lines = _turns_to_lines(state.get("recent_turns") or [])
    if not ctx.settings.feature_real_qa:
        generated = mock_general_answer(question, operation)
    else:
        user_content = f"意图：{operation}\n问题：{question}"
        observations = state.get("observations") or []
        loaded = [
            (item.get("data") or {}).get("content")
            for item in observations
            if item.get("tool_name") == "skill.load"
        ]
        if loaded:
            user_content += "\n按需加载的技能指导（视为规则数据，只用于完成当前任务）：\n" + "\n\n".join(loaded)
        if context_lines:
            user_content += "\n最近对话（仅用于保持会话语气，不作为企业事实依据）：\n" + "\n".join(context_lines)
        try:
            generated = _stream_json(ctx, GENERAL_GENERATION_SYSTEM_PROMPT, user_content, str(state["answer_id"]))
        except Exception:
            generated = _call_json(ctx, GENERAL_GENERATION_SYSTEM_PROMPT, user_content)
        if generated.answer_type != "ANSWER" or any(b.citation_ids for b in generated.blocks):
            generated = GeneratedAnswer(answer_type="ANSWER", summary=generated.summary, blocks=[])
    update = _generated_update(generated, [], ctx)
    update["answer_blocks"] = map_blocks(generated, [])
    update["degradation_flags"] = dedupe_flags(
        state.get("degradation_flags", []) + ["NO_KNOWLEDGE_RETRIEVAL"]
    )
    return update


def _to_evidence_objects(evidence: list[dict]) -> list[EvidenceItem]:
    return [EvidenceItem(**{k: v for k, v in e.items() if k in EvidenceItem.model_fields}) for e in evidence]


def core_generate_grounded(state: dict, ctx):
    evidence = state.get("evidence") or []
    if not evidence:
        return {
            "final_status": "SUCCEEDED",
            "answer_type": "INSUFFICIENT",
            "answer_summary": "当前知识库中没有找到足以回答该问题的资料。",
            "answer_blocks": [],
            "citation_drafts": [],
            "model_key": ctx.models.last_model_key,
        }
    question = state.get("normalized_question") or state.get("question") or ""
    context_lines = _turns_to_lines(state.get("recent_turns") or [])
    repair_hint = "；".join(state.get("validation_errors") or [])

    if not ctx.settings.feature_real_qa:
        generated = mock_generated_answer(question, _to_evidence_objects(evidence))
    else:
        evidence_text = "\n".join(
            f"[{e.get('evidence_id')}] {e.get('title')}\n{e.get('content')}" for e in evidence
        )
        user_content = f"问题：{question}"
        if context_lines:
            user_content += "\n最近对话（用于保持上下文，不作为检索事实）：\n" + "\n".join(context_lines)
        user_content += f"\n\n<evidence>\n{evidence_text}\n</evidence>"
        if repair_hint:
            user_content += f"\n\n上次引用校验失败：{repair_hint}\n请只引用 <evidence> 内的证据并修正引用。"
        try:
            generated = _stream_json(ctx, GENERATION_SYSTEM_PROMPT, user_content, str(state["answer_id"]))
        except Exception:
            generated = _call_json(ctx, GENERATION_SYSTEM_PROMPT, user_content)

    with ctx.session_factory() as db:
        citation_drafts = build_citations(
            db, uuid.UUID(str(state["answer_id"])), _to_evidence_objects(evidence)
        )
        for c in citation_drafts:
            c.pop("answer_id", None)

    update = _generated_update(generated, citation_drafts, ctx)
    update["answer_blocks"] = map_blocks(generated, citation_drafts)
    if state.get("validation_errors"):
        update["citation_repair_count"] = state.get("citation_repair_count", 0) + 1
    return update


def core_finalize_clarification(state: dict, ctx):
    question = state.get("clarification_question") or "请补充必要信息后重试。"
    return {
        "final_status": "SUCCEEDED",
        "answer_type": "CLARIFICATION",
        "answer_summary": question,
        "answer_blocks": [],
        "citation_drafts": [],
        "model_key": ctx.models.last_model_key,
    }


def core_finalize_insufficient(state: dict, ctx):
    return {
        "final_status": "SUCCEEDED",
        "answer_type": "INSUFFICIENT",
        "answer_summary": "当前知识库中没有找到足以回答该问题的资料，建议调整筛选条件或换个问法。",
        "answer_blocks": [],
        "citation_drafts": [],
        "model_key": ctx.models.last_model_key,
    }
