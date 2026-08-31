"""FakeFeishuProvider：确定性 mock 实现，供开发与测试使用。

- list_documents 返回固定样本，支持 query / resource_type / limit 过滤；
- get_metadata 对已知文档返回样本，对任意 token 合成元数据，保证提交可用；
- fetch_content 按 token 中的标记注入确定性错误，用于测试错误处理与重试：

    fail-once     首次调用抛 TRANSIENT，之后成功（验证重试恢复）
    transient     持续抛 TRANSIENT（验证重试耗尽 → FAILED）
    permanent     抛 VALIDATION（不可重试，立即 FAILED）
    auth-fail     抛 AUTH（授权失效 → 任务 FAILED，错误类别 AUTH）
    missing       抛 NOT_FOUND（文档不存在/被删除）
    ratelimit-once  首次抛 RATE_LIMIT，之后成功
    ratelimit     持续抛 RATE_LIMIT
    timeout-once  首次抛 TIMEOUT，之后成功
    timeout       持续抛 TIMEOUT

其余 token 正常返回内容。接入真实飞书后，工厂切到 RealFeishuProvider。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from .base import (
    AUTH,
    NOT_FOUND,
    RATE_LIMIT,
    TIMEOUT,
    TRANSIENT,
    VALIDATION,
    FeishuContent,
    FeishuDocument,
    FeishuDocumentProvider,
    FeishuError,
    FeishuListResult,
)

_DEFAULT_DOCS = [
    FeishuDocument(
        resource_token="wiki-hardware-spec",
        canonical_token="wiki-hardware-spec",
        title="AE 产品硬件规格",
        resource_type="wiki",
        modified_at=datetime(2026, 8, 12, 2, 0, tzinfo=timezone.utc),
        owner_name="测试团队",
        revision="mock-rev-1",
    ),
    FeishuDocument(
        resource_token="docx-product-whitepaper",
        canonical_token="docx-product-whitepaper",
        title="AE 产品白皮书",
        resource_type="docx",
        modified_at=datetime(2026, 8, 10, 7, 30, tzinfo=timezone.utc),
        owner_name="产品团队",
        revision="mock-rev-1",
    ),
    FeishuDocument(
        resource_token="wiki-seg-cases",
        canonical_token="wiki-seg-cases",
        title="SEG 问题案件沉淀",
        resource_type="wiki",
        modified_at=datetime(2026, 8, 8, 9, 15, tzinfo=timezone.utc),
        owner_name="SEG 支持团队",
        revision="mock-rev-1",
    ),
]

# 文档正文样本：key 为 token，value 为 (正文, 原始 payload)
_CONTENT = {
    "wiki-hardware-spec": (
        "AE 产品硬件规格\n\n当前型号列表：\n- T90000 配置 256GB 内存\n- T8000 配置 128GB 内存",
        {"blocks": [{"type": "heading", "text": "AE 产品硬件规格"}]},
    ),
    "docx-product-whitepaper": (
        "AE 产品白皮书\n\n本白皮书介绍 AE 产品的核心能力与技术架构。",
        {"blocks": [{"type": "paragraph", "text": "AE 产品白皮书"}]},
    ),
    "wiki-seg-cases": (
        "SEG 问题案件沉淀\n\n记录 SEG 支持团队的常见问题与处理过程。",
        {"blocks": [{"type": "paragraph", "text": "SEG 问题案件沉淀"}]},
    ),
}


class FakeFeishuProvider(FeishuDocumentProvider):
    def __init__(self, documents: list[FeishuDocument] | None = None):
        self._documents = list(documents if documents is not None else _DEFAULT_DOCS)
        self._by_token = {d.canonical_token: d for d in self._documents}
        # token → fetch_content 调用次数，供 fail-once / ratelimit-once / timeout-once 使用
        self._fetch_calls: dict[str, int] = defaultdict(int)

    def list_documents(
        self,
        *,
        user_access_token: str | None,
        query: str | None = None,
        resource_types: list[str] | None = None,
        page_token: str | None = None,
        limit: int = 20,
    ) -> FeishuListResult:
        items = self._documents
        if query:
            keyword = query.casefold()
            items = [d for d in items if keyword in d.title.casefold()]
        if resource_types:
            allowed = set(resource_types)
            items = [d for d in items if d.resource_type in allowed]
        start = int(page_token or 0) if str(page_token or "0").isdigit() else 0
        page = items[start : start + limit]
        next_cursor = str(start + limit) if start + limit < len(items) else None
        return FeishuListResult(items=page, next_cursor=next_cursor)

    def resolve_url(self, user_access_token: str | None, url: str) -> FeishuDocument:
        token, resource_type = _parse_url(url)
        return self.get_metadata(user_access_token, token, resource_type)

    def get_metadata(
        self, user_access_token: str | None, resource_token: str, resource_type: str
    ) -> FeishuDocument:
        known = self._by_token.get(resource_token)
        if known is not None:
            return known
        # 任意 token 合成元数据，保证提交与后续处理可用
        return FeishuDocument(
            resource_token=resource_token,
            canonical_token=resource_token,
            title=f"文档 {resource_token}",
            resource_type=resource_type,
            modified_at=datetime.now(timezone.utc),
            owner_name="未知用户",
            revision="mock-rev-1",
        )

    def fetch_content(
        self,
        user_access_token: str | None,
        resource_token: str,
        resource_type: str,
        *,
        source_url: str | None = None,
    ) -> FeishuContent:
        self._fetch_calls[resource_token] += 1
        n = self._fetch_calls[resource_token]

        marker = resource_token
        if "fail-once" in marker and n == 1:
            raise FeishuError(TRANSIENT, "MOCK_TRANSIENT", "模拟首次尝试失败，可重试", retryable=True)
        if "transient" in marker:
            raise FeishuError(TRANSIENT, "MOCK_TRANSIENT", "模拟持续可重试失败", retryable=True)
        if "permanent" in marker:
            raise FeishuError(VALIDATION, "MOCK_PERMANENT", "模拟不可重试失败", retryable=False)
        if "auth-fail" in marker:
            raise FeishuError(AUTH, "FEISHU_AUTH_EXPIRED", "飞书授权已失效", retryable=False)
        if "missing" in marker:
            raise FeishuError(NOT_FOUND, "DOC_NOT_FOUND", "文档不存在或已被删除", retryable=False)
        # "-once" 标记命中时短路：仅首次失败，之后成功（不落入下面的泛化标记）
        if "ratelimit-once" in marker:
            if n == 1:
                raise FeishuError(RATE_LIMIT, "FEISHU_RATE_LIMITED", "飞书接口限流", retryable=True)
        elif "ratelimit" in marker:
            raise FeishuError(RATE_LIMIT, "FEISHU_RATE_LIMITED", "飞书接口限流", retryable=True)
        if "timeout-once" in marker:
            if n == 1:
                raise FeishuError(TIMEOUT, "FEISHU_TIMEOUT", "飞书接口超时", retryable=True)
        elif "timeout" in marker:
            raise FeishuError(TIMEOUT, "FEISHU_TIMEOUT", "飞书接口超时", retryable=True)

        known = self._by_token.get(resource_token)
        title = known.title if known else f"文档 {resource_token}"
        text, payload = _CONTENT.get(resource_token, (f"{title}\n\n（mock 正文）", {"blocks": []}))
        return FeishuContent(
            title=title,
            text=text,
            content_type=resource_type,
            revision="mock-rev-1",
            modified_at=(known.modified_at if known else datetime.now(timezone.utc)),
            raw_payload={"token": resource_token, "type": resource_type, **payload},
        )


def _parse_url(url: str) -> tuple[str, str]:
    """从飞书 URL 提取 (token, resource_type)。支持 /wiki/{token}、/docx/{token}。"""
    lowered = url.casefold()
    for marker, resource_type in (("/wiki/", "wiki"), ("/docx/", "docx"), ("/sheets/", "sheet")):
        if marker in lowered:
            token = url.rsplit(marker, 1)[-1].split("?", 1)[0].rstrip("/")
            return token, resource_type
    raise FeishuError(VALIDATION, "UNSUPPORTED_URL", f"无法识别的飞书链接: {url}", retryable=False)
