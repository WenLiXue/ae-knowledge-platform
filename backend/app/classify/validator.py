"""分类输出校验与决策（DD-19 §8.4、DD-05 §7）。

校验链：JSON 解码 → Pydantic → 置信度 → code 合法 → 产品版本归属 →
evidence locator → 长度/数量 → null 语义。首次失败允许一次结构化修复调用；
仍失败进入任务重试，不用正则猜业务结果。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from pydantic import ValidationError

from .config import ClassificationConfig
from .schemas import ClassificationOutput, EvidenceBlock

_MAX_KEYWORDS = 20
_MAX_KEYWORD_LEN = 40
_MAX_SUMMARY_LEN = 800
_MAX_REASON_LEN = 1000
_MAX_EXCERPTS_PER_FIELD = 20
_MAX_EXCERPT_LEN = 300
_MAX_MISSING_FIELDS = 20

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    output: ClassificationOutput | None
    decision: str | None
    issues: list[ValidationIssue] = field(default_factory=list)
    valid: bool = False


def as_issue_dict(issue: ValidationIssue) -> dict:
    return {"code": issue.code, "message": issue.message}


def extract_json(raw_text: str) -> dict | None:
    """宽松提取 JSON 对象：优先完整对象，其次 Markdown 围栏内、再平衡大括号。"""
    if not raw_text:
        return None
    stripped = raw_text.strip()
    match = _FENCE_RE.search(stripped)
    candidate = match.group(1).strip() if match else stripped
    try:
        obj = json.loads(candidate)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    start = candidate.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(candidate)):
            ch = candidate[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(candidate[start : i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except (json.JSONDecodeError, ValueError):
                        pass
                    break
    return None


def _allowed_codes(taxonomy: dict) -> dict[str, set[str]]:
    return {
        "product_code": {str(p["code"]) for p in taxonomy.get("products") or []},
        "product_version_code": {str(v["code"]) for v in taxonomy.get("product_versions") or []},
        "document_type_code": {str(t["code"]) for t in taxonomy.get("document_types") or []},
        "product_form_code": {str(f["code"]) for f in taxonomy.get("product_forms") or []},
    }


def _version_to_product(taxonomy: dict) -> dict[str, str | None]:
    return {str(v["code"]): v.get("product_code") for v in taxonomy.get("product_versions") or []}


def _pydantic_summary(exc: ValidationError) -> str:
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(x) for x in first.get("loc", []))
    msg = first.get("msg", "校验失败")
    return f"{loc}: {msg}" if loc else msg


def has_valid_evidence(output: ClassificationOutput, locators: set[str]) -> bool:
    """至少一处有效证据：evidence 非空且所有 locator 都来自本次输入。"""
    for evidence in output.evidence:
        if evidence.locator_ids and all(loc in locators for loc in evidence.locator_ids):
            return True
    return False


def decide(output: ClassificationOutput, config: ClassificationConfig) -> str:
    """自动决策（DD-19 §8.4）：阈值不足、证据不足或矛盾程序转 UNCERTAIN。"""
    if output.relevance == "UNCERTAIN":
        return "UNCERTAIN"
    thresholds = config.thresholds
    has_evidence = any(e.locator_ids for e in output.evidence)
    if output.relevance == "RELEVANT":
        if (
            output.relevance_confidence >= float(thresholds.get("relevant", 0.8))
            and has_evidence
        ):
            return "RELEVANT"
        return "UNCERTAIN"
    if output.relevance == "IRRELEVANT":
        if (
            output.relevance_confidence >= float(thresholds.get("irrelevant", 0.9))
            and has_evidence
        ):
            return "IRRELEVANT"
        return "UNCERTAIN"
    return "UNCERTAIN"


def validate_output(
    raw_text: str,
    *,
    blocks: list[EvidenceBlock],
    taxonomy: dict,
    config: ClassificationConfig,
) -> ValidationResult:
    """按 DD-19 §8.4 顺序校验并给出最终程序决策。"""
    parsed = extract_json(raw_text)
    if parsed is None:
        return ValidationResult(None, None, [ValidationIssue("INVALID_JSON", "输出不是合法 JSON 对象")], False)

    try:
        output = ClassificationOutput.model_validate(parsed)
    except ValidationError as exc:
        return ValidationResult(
            None, None,
            [ValidationIssue("SCHEMA", f"输出不符合分类契约: {_pydantic_summary(exc)}")],
            False,
        )

    allowed = _allowed_codes(taxonomy)
    locators = {b.locator_id for b in blocks}
    version_product = _version_to_product(taxonomy)
    issues: list[ValidationIssue] = []

    # code 必须来自启用 taxonomy；未知返回 null，不猜测
    for field_name in ("product_code", "product_version_code", "document_type_code", "product_form_code"):
        code = getattr(output, field_name)
        if code is not None and code not in allowed[field_name]:
            issues.append(ValidationIssue("UNKNOWN_CODE", f"{field_name} 不在启用 taxonomy 中: {code}"))

    # 产品版本归属
    if output.product_code and output.product_version_code:
        expected_product = version_product.get(output.product_version_code)
        if expected_product is not None and expected_product != output.product_code:
            issues.append(
                ValidationIssue(
                    "VERSION_PRODUCT_MISMATCH",
                    f"产品版本 {output.product_version_code} 不属于产品 {output.product_code}",
                )
            )

    # evidence locator 必须真实存在于本次输入
    for evidence in output.evidence:
        for loc in evidence.locator_ids:
            if loc not in locators:
                issues.append(ValidationIssue("INVALID_LOCATOR", f"evidence 引用了不存在的 locator: {loc}"))

    # 长度/数量限制
    if len(output.keywords) > _MAX_KEYWORDS:
        issues.append(ValidationIssue("LIMIT", f"keywords 超过 {_MAX_KEYWORDS} 个"))
    for kw in output.keywords:
        if len(kw) > _MAX_KEYWORD_LEN:
            issues.append(ValidationIssue("LIMIT", "存在超长关键词"))
    if output.summary and len(output.summary) > _MAX_SUMMARY_LEN:
        issues.append(ValidationIssue("LIMIT", f"summary 超过 {_MAX_SUMMARY_LEN} 字符"))
    for evidence in output.evidence:
        if len(evidence.excerpts) > _MAX_EXCERPTS_PER_FIELD:
            issues.append(ValidationIssue("LIMIT", f"单个证据摘录超过 {_MAX_EXCERPTS_PER_FIELD} 条"))
        for excerpt in evidence.excerpts:
            if len(excerpt) > _MAX_EXCERPT_LEN:
                issues.append(ValidationIssue("LIMIT", "存在超长证据摘录"))
    for field_name, confidence in (output.field_confidence or {}).items():
        if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
            issues.append(ValidationIssue("CONFIDENCE_RANGE", f"field_confidence[{field_name}] 不在 [0,1]"))
    if len(output.missing_fields) > _MAX_MISSING_FIELDS:
        issues.append(ValidationIssue("LIMIT", "missing_fields 过多"))

    if issues:
        return ValidationResult(output, None, issues, False)

    decision = decide(output, config)
    return ValidationResult(output, decision, [], True)
