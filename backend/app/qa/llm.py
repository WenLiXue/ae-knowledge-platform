"""问答模型交互（DD-07 §5/§12/§18）。

- default_chat_fn：解析 QA 服务模型并调用 gateway.chat（外部调用不持 DB 事务）；
- understand_query：把问题改写为独立可检索问题（JSON 严格校验，首次失败允许一次修复）；
- generate_answer：基于证据生成结构化答案（Pydantic + 引用校验，一次修复）；
- mock_generated_answer：feature_real_qa=False 时的确定性预览答案（逐证据段落，不编造）。

日志不含正文/问题/证据/Token/密钥；只记 id/阶段/耗时/稳定错误码。
"""

from __future__ import annotations

import json
import logging
from typing import Callable

from pydantic import ValidationError

from ..llm.runtime import resolve_service_model
from ..model_gateway import create_gateway
from ..model_gateway.base import ChatRequest
from ..model_gateway.errors import GatewayError
from .prompts import (
    GENERAL_GENERATION_SYSTEM_PROMPT,
    GENERATION_SYSTEM_PROMPT,
    UNDERSTANDING_SYSTEM_PROMPT,
)
from .schemas import GeneratedAnswer, QueryUnderstanding

logger = logging.getLogger(__name__)


class QaError(Exception):
    """问答领域错误。category/code 稳定，retryable 决定任务是否重试。"""

    def __init__(self, category: str, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.category = category
        self.code = code
        self.message = message
        self.retryable = retryable


ChatFn = Callable[[list[dict]], str]


def chat_with_retry(
    gateway,
    model_name: str,
    messages: list[dict],
    *,
    max_tokens: int = 4096,
    retries: int = 3,
    response_format: dict | None = None,
):
    """调用 chat 并对空内容（CHAT_EMPTY）做有限重试——真实模型（deepseek-v4-flash）
    对长 prompt 偶发空返回。仍空则抛最后一次 GatewayError。"""
    import time

    last_error: GatewayError | None = None
    for attempt in range(retries + 1):
        try:
            resp = gateway.chat(
                ChatRequest(
                    model=model_name,
                    messages=messages,
                    max_tokens=max_tokens,
                    response_format=response_format,
                )
            )
            return resp.content
        except GatewayError as exc:
            if exc.code == "CHAT_EMPTY" and attempt < retries:
                last_error = exc
                time.sleep(0.5 * (attempt + 1))
                continue
            raise
    assert last_error is not None
    raise last_error


def default_chat_fn(db, messages: list[dict], *, max_tokens: int = 4096) -> str:
    """解析 QA 模型并调用 chat，返回回复文本。失败抛 LLMConfigError/GatewayError。"""
    resolved = resolve_service_model(db, "QA")
    gateway = create_gateway(resolved)
    return chat_with_retry(gateway, resolved.model_name, messages, max_tokens=max_tokens)


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _parse_json(text: str):
    cleaned = _strip_code_fence(text)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise QaError("SCHEMA", "QA_INVALID_JSON", "模型输出不是合法 JSON", retryable=False)
    return json.loads(cleaned[start : end + 1])


def _with_repair(call, parse_and_validate, error_hint: str):
    """首次失败带结构化错误调用一次修复；仍失败抛 QaError（进入任务重试）。"""
    try:
        return parse_and_validate(call())
    except (QaError, ValidationError, json.JSONDecodeError) as exc:
        hint = str(getattr(exc, "message", exc))
        try:
            return parse_and_validate(call(hint))
        except (QaError, ValidationError, json.JSONDecodeError) as exc2:
            raise QaError(
                "SCHEMA",
                "QA_SCHEMA_INVALID",
                f"模型输出校验失败: {hint}",
                retryable=False,
            ) from exc2


def understand_query(
    db,
    *,
    question: str,
    filters_text: str,
    context_lines: list[str],
    chat_fn: ChatFn | None = None,
) -> QueryUnderstanding:
    """查询理解（DD-07 §5）：改写为独立问题或请求澄清。"""
    chat = chat_fn or (lambda msgs: default_chat_fn(db, msgs))
    user_content = f"问题：{question}"
    if filters_text:
        user_content += f"\n当前筛选条件：{filters_text}"
    if context_lines:
        user_content += "\n最近对话（用于解析指代，不作为检索事实）：\n" + "\n".join(context_lines)

    def build(error_hint: str | None = None) -> list[dict]:
        messages = [{"role": "system", "content": UNDERSTANDING_SYSTEM_PROMPT}]
        content = user_content if error_hint is None else f"{user_content}\n\n上次输出校验失败：{error_hint}\n请重新输出合法 JSON。"
        messages.append({"role": "user", "content": content})
        return messages

    def parse_and_validate(content: str) -> QueryUnderstanding:
        data = _parse_json(content)
        parsed = QueryUnderstanding.model_validate(data)
        if parsed.clarification_needed:
            if not parsed.clarification_question:
                raise QaError("SCHEMA", "QA_CLARIFY_EMPTY", "澄清问题为空", retryable=False)
        elif not parsed.standalone_query.strip():
            raise QaError("SCHEMA", "QA_STANDALONE_EMPTY", "独立问题为空", retryable=False)
        return parsed

    return _with_repair(lambda hint=None: chat(build(hint)), parse_and_validate, "理解输出不符合要求")


def local_query_understanding(question: str) -> QueryUnderstanding | None:
    """无真实 QA 模型时识别明确的非知识库请求。

    只处理高置信度的短语；其余问题返回 None，由 Worker 保守地进入知识查询。
    """
    normalized = (question or "").strip().lower()
    if not normalized:
        return None
    if normalized in {"你好", "您好", "hi", "hello", "hey", "早上好", "下午好", "晚上好"}:
        return QueryUnderstanding(operation="CHAT", standalone_query=question)
    if any(token in normalized for token in ("谢谢", "感谢", "多谢")) and len(normalized) <= 40:
        return QueryUnderstanding(operation="CHAT", standalone_query=question)
    if any(token in normalized for token in ("你是谁", "你是什么", "介绍一下你", "怎么使用", "怎么用")):
        return QueryUnderstanding(operation="CHAT", standalone_query=question)
    if any(token in normalized for token in ("是什么意思", "什么是", "怎么理解", "概念是什么")):
        return QueryUnderstanding(operation="EXPLAIN", standalone_query=question)
    return None


def generate_answer(
    db,
    *,
    question: str,
    evidence_text: str,
    context_lines: list[str] | None = None,
    chat_fn: ChatFn | None = None,
) -> GeneratedAnswer:
    """基于证据生成答案（DD-07 §12）：JSON + Schema + 引用校验。"""
    chat = chat_fn or (lambda msgs: default_chat_fn(db, msgs))
    user_content = f"问题：{question}"
    if context_lines:
        user_content += "\n最近对话（用于保持上下文，不作为检索事实）：\n" + "\n".join(context_lines)
    user_content += f"\n\n<evidence>\n{evidence_text}\n</evidence>"

    def build(error_hint: str | None = None) -> list[dict]:
        messages = [{"role": "system", "content": GENERATION_SYSTEM_PROMPT}]
        content = user_content if error_hint is None else f"{user_content}\n\n上次输出校验失败：{error_hint}\n请重新输出合法 JSON。"
        messages.append({"role": "user", "content": content})
        return messages

    def parse_and_validate(content: str) -> GeneratedAnswer:
        data = _parse_json(content)
        return GeneratedAnswer.model_validate(data)

    return _with_repair(lambda hint=None: chat(build(hint)), parse_and_validate, "生成输出不符合要求")


def generate_general_answer(
    db,
    *,
    question: str,
    operation: str,
    context_lines: list[str] | None = None,
    chat_fn: ChatFn | None = None,
) -> GeneratedAnswer:
    """生成不依赖知识库证据的回答。

    该路径只接受 CHAT/EXPLAIN 这类由编排器判定为非企业事实的问题，
    因此不允许生成引用，也不走 RAG 生成 Prompt。
    """
    chat = chat_fn or (lambda msgs: default_chat_fn(db, msgs))
    user_content = f"意图：{operation}\n问题：{question}"
    if context_lines:
        user_content += "\n最近对话（仅用于保持会话语气，不作为企业事实依据）：\n" + "\n".join(context_lines)

    def build(error_hint: str | None = None) -> list[dict]:
        messages = [{"role": "system", "content": GENERAL_GENERATION_SYSTEM_PROMPT}]
        content = user_content if error_hint is None else f"{user_content}\n\n上次输出校验失败：{error_hint}\n请重新输出合法 JSON。"
        messages.append({"role": "user", "content": content})
        return messages

    def parse_and_validate(content: str) -> GeneratedAnswer:
        data = _parse_json(content)
        parsed = GeneratedAnswer.model_validate(data)
        if parsed.answer_type != "ANSWER":
            raise QaError("SCHEMA", "QA_GENERAL_TYPE_INVALID", "通用回答必须是 ANSWER", retryable=False)
        if any(block.citation_ids for block in parsed.blocks):
            raise QaError("SCHEMA", "QA_GENERAL_CITATION_INVALID", "通用回答不能包含知识库引用", retryable=False)
        return parsed

    return _with_repair(lambda hint=None: chat(build(hint)), parse_and_validate, "通用回答输出不符合要求")


def validate_generated(generated: GeneratedAnswer, evidence_ids: list[str]) -> None:
    """引用校验（DD-07 §12.3）：引用必须存在且事实 block 必须有引用。"""
    allowed = set(evidence_ids)
    for block in generated.blocks:
        if block.type in ("paragraph", "table", "list"):
            if not block.citation_ids:
                raise QaError("VALIDATION", "QA_BLOCK_NO_CITATION", "事实块缺少引用", retryable=False)
        unknown = [cid for cid in block.citation_ids if cid not in allowed]
        if unknown:
            raise QaError(
                "VALIDATION", "QA_CITATION_UNKNOWN", f"引用了不存在的证据: {unknown}", retryable=False
            )


def mock_generated_answer(question: str, evidence) -> GeneratedAnswer:
    """确定性预览答案（feature_real_qa=False 开发/测试用）：逐证据呈现，不编造事实。"""
    if not evidence:
        return GeneratedAnswer(
            answer_type="INSUFFICIENT",
            summary="当前知识库中没有找到足以回答该问题的资料。",
            blocks=[],
        )
    blocks = []
    for ev in evidence:
        content = ev.content
        if len(content) > 400:
            content = content[:400] + "…"
        blocks.append(
            {
                "type": "paragraph",
                "content": content,
                "citation_ids": [ev.evidence_id],
            }
        )
    return GeneratedAnswer(
        answer_type="ANSWER",
        summary=f"根据 {len(evidence)} 份来源资料整理（预览模式，未启用真实生成）：",
        blocks=blocks,
    )


def mock_general_answer(question: str, operation: str) -> GeneratedAnswer:
    """非真实 QA 模式下的确定性通用回答，确保“你好”等输入不会触发 RAG。"""
    normalized = question.strip().lower()
    if normalized in {"你好", "您好", "hi", "hello", "hey"} or any(
        token in normalized for token in ("你好", "您好")
    ):
        summary = "你好！我是知识智能助手，可以帮你查询企业产品资料、部署方式和问题案例。"
    elif any(token in normalized for token in ("谢谢", "感谢", "多谢")):
        summary = "不客气。如果还需要查询产品资料，直接告诉我你的问题即可。"
    elif any(token in normalized for token in ("你是谁", "你是什么", "介绍一下你")):
        summary = "我是企业知识智能助手，负责理解问题并在需要时从知识库检索可追溯资料。"
    else:
        summary = "这是一个通用解释请求；如果你要核对具体产品或版本事实，请补充产品名称或直接发起知识查询。"
    return GeneratedAnswer(answer_type="ANSWER", summary=summary, blocks=[])
