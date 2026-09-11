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
from ...qa.schemas import GeneratedAnswer, GeneratedBlock
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


GENERATION_TIMEOUT_SECONDS = 45.0
# 为降级回答预留一小段时间，避免结构化输出一超时就把整次回答判失败。
PRIMARY_GENERATION_TIMEOUT_SECONDS = 35.0
FALLBACK_TIMEOUT_SECONDS = 10.0
MAX_PROMPT_CHARS = 24000
MAX_EVIDENCE_COUNT = 8
MAX_EVIDENCE_CHARS = 1800


def _timeout():
    from ..errors import AgentError
    return AgentError("LLM_GENERATION_TIMEOUT", "回答生成超时，请缩小问题范围后重试。", retryable=False)


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _timeout()
    return remaining


def _load_draft(ctx, answer_id: str) -> str:
    """读取流式阶段已经落库的可读草稿。草稿不是权威答案，但可用于降级收敛。"""
    from ...db.models.conversation import Answer

    try:
        with ctx.session_factory() as db:
            answer = db.get(Answer, uuid.UUID(str(answer_id)))
            return (answer.draft_text or "").strip() if answer is not None else ""
    except Exception:
        return ""


def _fallback_plain(ctx, user_content: str, answer_id: str, deadline: float) -> GeneratedAnswer:
    """结构化输出超时后的短文本兜底，保证已有证据仍能形成可读回答。"""
    fallback_prompt = (
        "你是企业知识助手。请仅依据用户问题和给定资料，输出简洁、可直接展示给用户的中文答案。"
        "不要输出 JSON、不要输出代码围栏、不要编造资料中没有的事实；资料不足时明确说明。"
    )
    chunks: list[str] = []
    for chunk in ctx.models.stream_chat(
        [{"role": "system", "content": fallback_prompt}, {"role": "user", "content": user_content}],
        max_tokens=1200,
        timeout_seconds=min(FALLBACK_TIMEOUT_SECONDS, _remaining(deadline)),
    ):
        _remaining(deadline)
        chunks.append(chunk)
    text = "".join(chunks).strip()
    if not text:
        raise _timeout()
    return GeneratedAnswer(answer_type="PARTIAL", summary=text, blocks=[])


def _generate(ctx, system_prompt, user_content, answer_id):
    from ..errors import AgentError
    from ...model_gateway.errors import GatewayError

    deadline = time.monotonic() + min(
        GENERATION_TIMEOUT_SECONDS, ctx.deadline - ctx.clock().timestamp()
    )
    primary_deadline = min(deadline, time.monotonic() + PRIMARY_GENERATION_TIMEOUT_SECONDS)
    user_content = user_content[:max(0, MAX_PROMPT_CHARS - len(system_prompt))]
    try:
        try:
            return _stream_json(ctx, system_prompt, user_content, answer_id, primary_deadline)
        except (TimeoutError, AgentError) as exc:
            if isinstance(exc, AgentError) and exc.code not in ("LLM_GENERATION_TIMEOUT",):
                raise
            draft = _load_draft(ctx, answer_id)
            if draft:
                return GeneratedAnswer(answer_type="PARTIAL", summary=draft[:12000], blocks=[])
            return _fallback_plain(ctx, user_content, answer_id, deadline)
        except GatewayError as exc:
            if exc.code == "TIMEOUT":
                draft = _load_draft(ctx, answer_id)
                if draft:
                    return GeneratedAnswer(answer_type="PARTIAL", summary=draft[:12000], blocks=[])
                return _fallback_plain(ctx, user_content, answer_id, deadline)
            if exc.category in ("AUTH", "CONFIG", "VALIDATION"):
                raise
        except (AttributeError, NotImplementedError, ValueError):
            pass
        remaining = min(FALLBACK_TIMEOUT_SECONDS, _remaining(deadline))
        result = _parse_generated(ctx.models.chat(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}],
            timeout_seconds=remaining,
        ))
        _remaining(deadline)
        return result
    except (TimeoutError, GatewayError) as exc:
        if isinstance(exc, TimeoutError) or exc.code == "TIMEOUT":
            raise _timeout() from exc
        raise AgentError("GENERATION_FAILED", "模型生成失败，请稍后重试。", retryable=False) from exc
    except ValueError as exc:
        raise AgentError("GENERATION_FAILED", "模型回答格式无效，请稍后重试。", retryable=False) from exc


def _stream_json(ctx, system_prompt: str, user_content: str, answer_id: str, deadline: float) -> GeneratedAnswer:
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

    for chunk in ctx.models.stream_chat(
        messages,
        timeout_seconds=_remaining(deadline),
    ):
        _remaining(deadline)
        chunks.append(chunk)
        raw = "".join(chunks)
        match = re.search(r'"summary"\s*:\s*"((?:\\.|[^"\\])*)', raw)
        if match:
            try:
                persist_draft(json.loads('"' + match.group(1) + '"'))
            except ValueError:
                pass
    _remaining(deadline)
    return _parse_generated("".join(chunks))

def _generated_update(generated: GeneratedAnswer, citation_drafts: list[dict], ctx) -> dict:
    update = {
        "generation_completed": True,
        "answer_type": generated.answer_type,
        "answer_summary": generated.summary,
        "citation_drafts": citation_drafts,
        "model_key": ctx.models.last_model_key,
        "final_status": "SUCCEEDED",
    }
    if generated.answer_type == "PARTIAL":
        update["degradation_flags"] = ["LLM_GENERATION_PARTIAL"]
    return update


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
            user_content += "\n最近对话（仅用于保持会话语气，不作为企业事实依据）：\n" + "\n".join(context_lines)[:3000]
        generated = _generate(ctx, GENERAL_GENERATION_SYSTEM_PROMPT, user_content, str(state["answer_id"]))
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


def _evidence_fallback(evidence: list[dict]) -> GeneratedAnswer:
    """模型完全无输出时的通用证据兜底，不依赖具体业务领域。"""
    blocks: list[GeneratedBlock] = []
    for item in evidence[:5]:
        evidence_id = str(item.get("evidence_id") or "")
        title = str(item.get("title") or "相关资料")[:160]
        raw_content = str(item.get("content") or "")
        # 兜底路径不猜测或重排表格；保留模型/文档解析器生成的 Markdown，
        # 交给前端 GFM 渲染。仅截断飞书附件元数据，避免把内部 token 展示给用户。
        content = raw_content.split(" [{'", 1)[0].split(" [{\"", 1)[0].strip()[:2000]
        if not content:
            continue
        blocks.append(
            GeneratedBlock(
                type="paragraph",
                content=f"{title}：{content}",
                citation_ids=[evidence_id] if evidence_id else [],
            )
        )
    return GeneratedAnswer(
        answer_type="PARTIAL",
        summary="模型生成响应较慢，先展示已检索到的相关资料摘要。",
        blocks=blocks,
    )


def _extract_evidence_table(content: str, evidence_id: str) -> GeneratedBlock | None:
    """将常见的 Markdown 管道表格压缩为可读的关键列。"""
    # 优先按行解析，避免把说明文字和分隔线单元格误当成表格数据。
    lines = [line.strip() for line in content.splitlines() if line.strip()]

    def cells(line: str) -> list[str]:
        if "|" not in line:
            return []
        return [" ".join(item.split())[:180] for item in line.strip("|").split("|")]

    separator_index = next(
        (
            index
            for index, line in enumerate(lines)
            if len(cells(line)) >= 2
            and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells(line))
        ),
        None,
    )
    if separator_index is None or separator_index == 0:
        return None
    headers = cells(lines[separator_index - 1])
    # 单字段纵向列表（例如“CPU截图 | 80W | 8 | …”）不是表格，
    # 不能为了兜底展示而强行包装成一列表格。
    if len(headers) < 3:
        return None
    width = len(headers)
    if width <= 0:
        return None

    rows: list[list[str]] = []
    for line in lines[separator_index + 1 :]:
        row = cells(line)
        if len(row) != width:
            # 后续的附件/mention 元数据不是表格行，遇到它即可停止。
            if "fileToken" in line or "mentionType" in line or line.startswith("[{"):
                break
            continue
        if any(value not in ("", "—") for value in row):
            rows.append(row)
        if len(rows) >= 12:
            break

    # 少数解析器会把表格压成单行，保留旧的 token 解析作为兼容兜底。
    if not rows:
        separator = re.search(r"\|\s*-{3,}[^\n]*", content)
        if separator is None:
            return None
        data = [
            " ".join(item.split())[:180]
            for item in content[separator.end() :].split("|")
            if " ".join(item.split())
            and not item.strip().startswith(("[{", "{"))
            and "fileToken" not in item
            and "mentionType" not in item
        ]
        for offset in range(0, len(data), width):
            row = data[offset : offset + width]
            if len(row) < width:
                break
            rows.append(row)
            if len(rows) >= 12:
                break

    preferred = ["厂商", "AE型号", "防病毒吞吐", "网络吞吐", "CPU", "内存", "硬盘", "板载网卡"]
    selected = [index for index, header in enumerate(headers) if any(name in header for name in preferred)]
    # 至少命中两个业务字段才认为是可安全展示的规格表；否则交给段落渲染。
    if len(selected) < 2:
        return None
    columns = [headers[index] for index in selected]
    selected_rows = [[row[index] if index < len(row) else "—" for index in selected] for row in rows]
    if not selected_rows:
        return None
    return GeneratedBlock(
        type="table",
        content={"columns": columns, "rows": selected_rows},
        citation_ids=[evidence_id] if evidence_id else [],
    )


def core_generate_grounded(state: dict, ctx):
    evidence = (state.get("evidence") or [])[:MAX_EVIDENCE_COUNT]
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
            f"[{e.get('evidence_id')}] {str(e.get('title') or '')[:200]}\n{str(e.get('content') or '')[:MAX_EVIDENCE_CHARS]}" for e in evidence
        )
        user_content = f"问题：{question[:3000]}"
        if context_lines:
            user_content += "\n最近对话（用于保持上下文，不作为检索事实）：\n" + "\n".join(context_lines)[:3000]
        user_content += f"\n\n<evidence>\n{evidence_text}\n</evidence>"
        if repair_hint:
            user_content += f"\n\n上次引用校验失败：{repair_hint}\n请只引用 <evidence> 内的证据并修正引用。"
        try:
            generated = _generate(ctx, GENERATION_SYSTEM_PROMPT, user_content, str(state["answer_id"]))
        except Exception as exc:
            # 模型完全没有返回内容时，检索证据仍然是可用结果；将其安全收敛为部分回答。
            from ..errors import AgentError

            if isinstance(exc, AgentError) and exc.code == "LLM_GENERATION_TIMEOUT":
                generated = _evidence_fallback(evidence)
            else:
                raise

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
