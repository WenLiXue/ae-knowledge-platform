"""动作目录与脱敏策略（DD-17 §6.2）。

- 动作注册表：稳定动作码 → 模块、目标类型、允许审计的变更字段、是否记录失败、风险等级。
  未知动作直接拒绝写入，避免自由文本污染查询口径。
- 脱敏采用“默认拒绝 + 白名单允许”：字段名匹配敏感模式（递归）即拒绝保存；
  字符串有单字段与事件总大小上限，超限保存截断标记与原值摘要。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

# 递归拒绝的字段名子串（大小写不敏感）。命中即不保存值本身。
REDACTED_FIELD_PATTERNS = (
    "password",
    "secret",
    "token",
    "cookie",
    "authorization",
    "api_key",
    "content",
    "body",
    "prompt",
)

REDACTED_PLACEHOLDER = "[REDACTED]"

# 单个字符串字段最大长度（截断后）
MAX_FIELD_LEN = 512
# 单个事件内字符串总大小上限
MAX_EVENT_STR_LEN = 16_000
# summary 上限（对齐表定义 varchar(512)）
MAX_SUMMARY_LEN = 512

_LLM_CHANGE_FIELDS = (
    "provider",
    "base_url",
    "model",
    "temperature",
    "top_p",
    "max_tokens",
    "timeout_seconds",
    "classification_model",
    "embedding_model",
    "enabled",
    "has_api_key",
)


@dataclass(frozen=True)
class ActionSpec:
    action: str
    module: str
    target_type: str | None
    change_fields: tuple[str, ...] = ()
    record_failure: bool = True
    risk: str = "medium"  # low / medium / high
    # 变更字段展示名（脱敏后的稳定文案），用于 summary 拼接
    labels: dict[str, str] = field(default_factory=dict)


def _spec(action: str, module: str, target_type: str | None, change_fields=(), *, risk: str = "medium", record_failure: bool = True) -> ActionSpec:
    labels = {f: f for f in change_fields}
    return ActionSpec(action, module, target_type, tuple(change_fields), record_failure, risk, labels)


def _llm_spec() -> ActionSpec:
    labels = {
        "provider": "服务商", "base_url": "Base URL", "model": "模型",
        "temperature": "温度", "top_p": "Top P", "max_tokens": "最大 Token",
        "timeout_seconds": "超时秒数", "classification_model": "分类模型",
        "embedding_model": "Embedding 模型", "enabled": "启用状态",
        "has_api_key": "API Key 是否已配置",
    }
    return ActionSpec(
        "config.llm.update", "CONFIG", "LLM_CONFIG",
        _LLM_CHANGE_FIELDS, True, "high", labels,
    )


_LLM_MODEL_FIELDS = (
    "name", "model_type", "provider", "base_url", "model_name", "enabled", "has_api_key",
)

_LLM_MODEL_LABELS = {
    "name": "配置名称", "model_type": "模型类型", "provider": "服务商",
    "base_url": "Base URL", "model_name": "Model 名称", "enabled": "启用状态",
    "has_api_key": "API Key 是否已配置", "used_by": "引用服务",
}


def _llm_model_spec(action: str, *, with_used_by: bool = False) -> ActionSpec:
    fields = _LLM_MODEL_FIELDS + (("used_by",) if with_used_by else ())
    return ActionSpec(action, "CONFIG", "LLM_MODEL", fields, True, "high", _LLM_MODEL_LABELS)


def _binding_spec() -> ActionSpec:
    labels = {
        "QA": "智能问答", "DOCUMENT_CLASSIFICATION": "文档自动分类",
        "DOCUMENT_EMBEDDING": "文档向量化", "RETRIEVAL_RERANK": "检索重排",
    }
    fields = ("QA", "DOCUMENT_CLASSIFICATION", "DOCUMENT_EMBEDDING", "RETRIEVAL_RERANK")
    return ActionSpec("config.llm.binding.update", "CONFIG", "LLM_BINDING", fields, True, "high", labels)


# 代码级动作注册表。动作码为稳定枚举；新增动作必须在此登记。
ACTION_REGISTRY: dict[str, ActionSpec] = {
    # ---- AUTH ----
    "auth.login": _spec("auth.login", "AUTH", None, risk="medium"),
    "auth.logout": _spec("auth.logout", "AUTH", None, risk="low"),
    "auth.feishu.bind": _spec("auth.feishu.bind", "AUTH", "USER", risk="high"),
    "auth.feishu.unbind": _spec("auth.feishu.unbind", "AUTH", "USER", risk="high"),
    # ---- CONFIG：LLM 配置 ----
    "config.llm.update": _llm_spec(),
    # 模型管理与服务配置（DD-20 §13）
    "config.llm.model.create": _llm_model_spec("config.llm.model.create"),
    "config.llm.model.update": _llm_model_spec("config.llm.model.update"),
    "config.llm.model.enable": _llm_model_spec("config.llm.model.enable"),
    "config.llm.model.disable": _llm_model_spec("config.llm.model.disable", with_used_by=True),
    "config.llm.binding.update": _binding_spec(),
    # ---- CONFIG：来源优先级 ----
    "config.source_priority.update": _spec(
        "config.source_priority.update", "CONFIG", "SOURCE_PRIORITY", ("priority",), risk="medium"
    ),
    # ---- CONFIG：目录项 ----
    "config.catalog.product.create": _spec("config.catalog.product.create", "CONFIG", "PRODUCT", ("code", "name", "status", "sort_order"), risk="medium"),
    "config.catalog.product.update": _spec("config.catalog.product.update", "CONFIG", "PRODUCT", ("name", "status", "sort_order"), risk="medium"),
    "config.catalog.product.enable": _spec("config.catalog.product.enable", "CONFIG", "PRODUCT", ("status",), risk="medium"),
    "config.catalog.product.disable": _spec("config.catalog.product.disable", "CONFIG", "PRODUCT", ("status",), risk="medium"),
    "config.catalog.product.delete": _spec("config.catalog.product.delete", "CONFIG", "PRODUCT", risk="high"),
    "config.catalog.version.create": _spec("config.catalog.version.create", "CONFIG", "PRODUCT_VERSION", ("version_code", "big_version", "release_date", "status", "sort_order"), risk="medium"),
    "config.catalog.version.update": _spec("config.catalog.version.update", "CONFIG", "PRODUCT_VERSION", ("version_code", "big_version", "release_date", "status", "sort_order"), risk="medium"),
    "config.catalog.version.enable": _spec("config.catalog.version.enable", "CONFIG", "PRODUCT_VERSION", ("status",), risk="medium"),
    "config.catalog.version.disable": _spec("config.catalog.version.disable", "CONFIG", "PRODUCT_VERSION", ("status",), risk="medium"),
    "config.catalog.version.delete": _spec("config.catalog.version.delete", "CONFIG", "PRODUCT_VERSION", risk="high"),
    "config.catalog.document_type.create": _spec("config.catalog.document_type.create", "CONFIG", "DOCUMENT_TYPE", ("code", "name", "description", "status", "sort_order"), risk="medium"),
    "config.catalog.document_type.update": _spec("config.catalog.document_type.update", "CONFIG", "DOCUMENT_TYPE", ("name", "description", "status", "sort_order"), risk="medium"),
    "config.catalog.document_type.enable": _spec("config.catalog.document_type.enable", "CONFIG", "DOCUMENT_TYPE", ("status",), risk="medium"),
    "config.catalog.document_type.disable": _spec("config.catalog.document_type.disable", "CONFIG", "DOCUMENT_TYPE", ("status",), risk="medium"),
    "config.catalog.document_type.delete": _spec("config.catalog.document_type.delete", "CONFIG", "DOCUMENT_TYPE", risk="high"),
    "config.catalog.product_form.create": _spec("config.catalog.product_form.create", "CONFIG", "PRODUCT_FORM", ("code", "name", "status", "sort_order"), risk="medium"),
    "config.catalog.product_form.update": _spec("config.catalog.product_form.update", "CONFIG", "PRODUCT_FORM", ("name", "status", "sort_order"), risk="medium"),
    "config.catalog.product_form.enable": _spec("config.catalog.product_form.enable", "CONFIG", "PRODUCT_FORM", ("status",), risk="medium"),
    "config.catalog.product_form.disable": _spec("config.catalog.product_form.disable", "CONFIG", "PRODUCT_FORM", ("status",), risk="medium"),
    "config.catalog.product_form.delete": _spec("config.catalog.product_form.delete", "CONFIG", "PRODUCT_FORM", risk="high"),
    # ---- CLASSIFICATION：人工确认（DD-19 §9） ----
    "classification.pending.confirm_relevant": _spec(
        "classification.pending.confirm_relevant", "CLASSIFICATION", "CLASSIFICATION_PENDING",
        ("relevance", "product_code", "product_version_code", "document_type_code",
         "product_form_code", "is_domestic", "module_name", "business_topic", "summary",
         "keywords"), risk="high",
    ),
    "classification.pending.confirm_irrelevant": _spec(
        "classification.pending.confirm_irrelevant", "CLASSIFICATION", "CLASSIFICATION_PENDING",
        ("relevance", "offline_reason"), risk="high",
    ),
    "classification.pending.reclassify": _spec(
        "classification.pending.reclassify", "CLASSIFICATION", "CLASSIFICATION_PENDING",
        ("relevance", "config_revision", "model_key"), risk="high",
    ),
    # ---- AUDIT ----
    "audit.query": _spec("audit.query", "AUDIT", "AUDIT_LOG", risk="low"),
    "audit.view_detail": _spec("audit.view_detail", "AUDIT", "AUDIT_LOG", risk="medium"),
    "audit.export": _spec("audit.export", "AUDIT", "AUDIT_EXPORT", risk="high"),
    "user.query": _spec("user.query", "USER", "USER", risk="low"),
    "user.view": _spec("user.view", "USER", "USER", risk="low"),
    "user.update": _spec("user.update", "USER", "USER", ("display_name", "status", "is_admin"), risk="high"),
    "user.enable": _spec("user.enable", "USER", "USER", ("status",), risk="high"),
    "user.disable": _spec("user.disable", "USER", "USER", ("status",), risk="high"),
    "user.role.change": _spec("user.role.change", "USER", "USER", ("is_admin",), risk="high"),
    "conversation.admin.list": _spec("conversation.admin.list", "CONVERSATION", "CONVERSATION", risk="low"),
    "conversation.admin.view": _spec("conversation.admin.view", "CONVERSATION", "CONVERSATION", risk="medium"),
}

# 风险等级 ≥ 该值判定为高风险（用于前端高亮/导出提示）
HIGH_RISK = "high"


class UnknownActionError(Exception):
    """动作码未在注册表中登记。"""

    def __init__(self, action: str):
        super().__init__(f"未知审计动作: {action}")
        self.action = action


def get_spec(action: str) -> ActionSpec:
    try:
        return ACTION_REGISTRY[action]
    except KeyError:
        raise UnknownActionError(action) from None


def is_known(action: str) -> bool:
    return action in ACTION_REGISTRY


# ---- 脱敏 ----

def _matches_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(pattern in lowered for pattern in REDACTED_FIELD_PATTERNS)


def _truncate(value: str, max_len: int) -> str:
    if len(value) <= max_len:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return value[:max_len] + f"…[截断 {digest}]"


def sanitize_text(value: str, max_len: int = MAX_FIELD_LEN) -> str:
    """清除控制字符（保留 \\t），并截断到上限。"""
    cleaned = "".join(ch for ch in value if ch == "\t" or (ord(ch) >= 0x20 and ord(ch) != 0x7F))
    return _truncate(cleaned, max_len)


class _Budget:
    def __init__(self, limit: int = MAX_EVENT_STR_LEN):
        self.limit = limit
        self.spent = 0

    def take(self, length: int) -> bool:
        self.spent += length
        return self.spent <= self.limit


def redact_value(key: str, value, budget: _Budget | None = None) -> object:
    """递归脱敏单个值。

    默认拒绝：任何层级的字段名命中敏感模式即替换为占位符；
    其余值做控制字符清理与长度截断，并受事件总大小预算约束。
    """
    budget = budget or _Budget()
    if _matches_sensitive_key(key):
        return REDACTED_PLACEHOLDER
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for k, v in value.items():
            result[str(k)] = redact_value(str(k), v, budget)
        return result
    if isinstance(value, list):
        return [redact_value(key, v, budget) for v in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = str(value)
    if not budget.take(len(text)):
        return f"[超限 {_truncate(text, 64)}]"
    return sanitize_text(text)


def filter_changes(spec: ActionSpec, changes: list[dict]) -> list[dict]:
    """按动作白名单过滤并脱敏字段级变更列表。

    入参形如 [{"field": "name", "before": ..., "after": ...}]；
    返回仅包含白名单字段、且做递归脱敏与截断的列表。
    """
    allowed = set(spec.change_fields)
    budget = _Budget()
    result: list[dict] = []
    for change in changes:
        field = str(change.get("field", ""))
        if field not in allowed:
            continue
        result.append(
            {
                "field": field,
                "before": redact_value(field, change.get("before"), budget),
                "after": redact_value(field, change.get("after"), budget),
            }
        )
    return result


def redact_metadata(metadata: dict | None) -> dict:
    """对整个补充元数据字典做递归脱敏。"""
    return redact_value("metadata", metadata or {})  # type: ignore[return-value]


def clean_summary(summary: str) -> str:
    return sanitize_text(summary, MAX_SUMMARY_LEN)
