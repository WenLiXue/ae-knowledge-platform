"""RealFeishuProvider：基于飞书开放平台 OpenAPI 的真实实现。

- 应用凭据（app_id / app_secret）只从构造参数读取，不写入代码；
- 使用 tenant_access_token 作为应用级凭证，用户文档接口仍需 user_access_token（OAuth 提供）；
- 错误统一映射为 FeishuError 分类（AUTH / NOT_FOUND / RATE_LIMIT / TIMEOUT / TRANSIENT）；
- http_client 可注入（如 httpx.MockTransport），用于错误映射测试。

注意：飞书各接口的确切路径与返回结构随租户/版本演进，本实现按官方文档常见形态编写，
上线前需用真实应用凭据对端点与错误码做一次联调校正（见 docstring 中标注）。
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import httpx

from ..core.logging import log_external_call
from .base import (
    AUTH,
    NOT_FOUND,
    PERMISSION,
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

# 飞书常见错误码 → 分类（联调时按租户实际返回校正）
_FEISHU_ERROR_CODE_MAP: dict[int, str] = {
    910002: RATE_LIMIT,        # 接口限流
    99991663: AUTH,            # tenant_access_token 无效/过期
    99991664: AUTH,            # access_token 无效/过期
    99991665: AUTH,            # access_token 过期
    1061002: NOT_FOUND,        # 文档不存在
    215110: PERMISSION,        # 无权限访问该资源
    99991672: PERMISSION,      # 无权限（缺 scope 或未授权该接口）
}


class RealFeishuProvider(FeishuDocumentProvider):
    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        base_url: str = "https://open.feishu.cn",
        timeout_seconds: float = 10.0,
        http_client: httpx.Client | None = None,
    ):
        self._app_id = app_id
        self._app_secret = app_secret
        self._base_url = base_url.rstrip("/")
        self._http = http_client or httpx.Client(
            timeout=httpx.Timeout(timeout_seconds), follow_redirects=True
        )
        self._tenant_token: str | None = None
        self._tenant_token_expires_at: float = 0.0

    # ---- 应用级凭证 ----

    def _tenant_access_token(self) -> str:
        if self._tenant_token and time.time() < self._tenant_token_expires_at:
            return self._tenant_token
        # 该接口的 tenant_access_token 在响应顶层，不在 data 内
        body = self._request(
            "POST", "/open-apis/auth/v3/tenant_access_token/internal", token=None,
            json={"app_id": self._app_id, "app_secret": self._app_secret},
        )
        token = body.get("tenant_access_token", "")
        expire = body.get("expire", 7200)
        self._tenant_token = token
        self._tenant_token_expires_at = time.time() + expire - 60  # 提前 60s 续期
        return token

    # ---- 统一请求与错误映射 ----

    def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        url = f"{self._base_url}{path}"
        start = time.perf_counter()
        status_code: int | None = None
        result = "ok"
        try:
            try:
                resp = self._http.request(method, url, headers=headers, json=json, params=params)
                status_code = resp.status_code
            except httpx.TimeoutException as exc:
                result = "timeout"
                raise FeishuError(TIMEOUT, "FEISHU_TIMEOUT", f"飞书接口超时: {path}", retryable=True) from exc
            except httpx.HTTPError as exc:
                result = "network_error"
                raise FeishuError(TRANSIENT, "FEISHU_NETWORK", f"飞书网络错误: {exc}", retryable=True) from exc

            if resp.status_code == 429:
                result = "rate_limited"
                raise FeishuError(RATE_LIMIT, "FEISHU_RATE_LIMITED", "飞书接口限流", retryable=True)
            if resp.status_code in (401, 403):
                result = "auth_expired"
                raise FeishuError(AUTH, "FEISHU_AUTH_EXPIRED", "飞书授权失效", retryable=False)
            if resp.status_code == 404:
                result = "not_found"
                raise FeishuError(NOT_FOUND, "DOC_NOT_FOUND", "资源不存在", retryable=False)

            try:
                body = resp.json()
            except ValueError:
                result = "bad_json"
                raise FeishuError(TRANSIENT, "FEISHU_BAD_RESPONSE", "飞书返回非 JSON", retryable=True) from None

            code = int(body.get("code", 0))
            if code != 0:
                category = _FEISHU_ERROR_CODE_MAP.get(code, TRANSIENT)
                retryable = category in (RATE_LIMIT, TIMEOUT, TRANSIENT)
                result = f"feishu_{code}"
                raise FeishuError(category, f"FEISHU_{code}", str(body.get("msg", "未知错误")), retryable=retryable)
            # 返回完整响应体：有的接口（token 类）字段在顶层，其余在 data 内
            return body
        finally:
            log_external_call(
                dependency="feishu",
                method=method,
                path=path,
                duration_ms=(time.perf_counter() - start) * 1000,
                status=status_code,
                result=result,
            )

    # ---- 文档发现 ----

    def list_documents(
        self,
        *,
        user_access_token: str | None,
        query: str | None = None,
        resource_types: list[str] | None = None,
        page_token: str | None = None,
        limit: int = 20,
    ) -> FeishuListResult:
        if user_access_token is None:
            raise FeishuError(AUTH, "USER_TOKEN_MISSING", "缺少用户访问凭证", retryable=False)
        if query:
            # 有关键字：搜索云文档（需搜索 scope）
            body = self._request(
                "POST", "/open-apis/suite/docs-api/search/object", token=user_access_token,
                json={"search_key": query, "count": limit},
            )
            data = body.get("data", {})
            items = [_entity_to_document(e) for e in (data.get("entities", []) or [])]
            return FeishuListResult(items=items, next_cursor=data.get("page_token"))
        # 无关键字：列出云盘最近文件（drive:drive:readonly），便于发现页直接展示
        params: dict[str, Any] = {"page_size": limit, "order_by": "EditedTime", "direction": "DESC"}
        if page_token:
            params["page_token"] = page_token
        body = self._request(
            "GET", "/open-apis/drive/v1/files", token=user_access_token, params=params,
        )
        data = body.get("data", {})
        files = data.get("files", []) or []
        items = [_drive_file_to_document(f) for f in files]
        return FeishuListResult(items=items, next_cursor=data.get("next_page_token"))

    def resolve_url(self, user_access_token: str | None, url: str) -> FeishuDocument:
        token, resource_type = _parse_url(url)
        return self.get_metadata(user_access_token, token, resource_type)

    def get_metadata(
        self, user_access_token: str | None, resource_token: str, resource_type: str
    ) -> FeishuDocument:
        if user_access_token is None:
            raise FeishuError(AUTH, "USER_TOKEN_MISSING", "缺少用户访问凭证", retryable=False)
        if resource_type == "wiki":
            body = self._request(
                "GET", "/open-apis/wiki/v2/spaces/get_node", token=user_access_token,
                params={"token": resource_token},
            )
            node = body.get("data", {}).get("node", {})
            obj_token = node.get("obj_token", resource_token)
            title = node.get("title", resource_token)
            modified = _parse_timestamp(node.get("modify_time"))
            return FeishuDocument(
                resource_token=obj_token,
                canonical_token=obj_token,
                title=title,
                resource_type=_obj_type_to_resource_type(node.get("obj_type")),
                modified_at=modified,
                url=None,
                node_token=resource_token,
                extra={"obj_token": obj_token, "node_token": resource_token},
            )
        body = self._request(
            "GET", f"/open-apis/docx/v1/documents/{resource_token}", token=user_access_token,
        )
        doc = body.get("data", {}).get("document", {})
        return FeishuDocument(
            resource_token=resource_token,
            canonical_token=resource_token,
            title=doc.get("title", resource_token),
            resource_type=resource_type,
            modified_at=_parse_timestamp(doc.get("create_time")),
            revision=str(doc.get("revision", "")),
            url=None,
        )

    def fetch_content(
        self, user_access_token: str | None, resource_token: str, resource_type: str
    ) -> FeishuContent:
        if user_access_token is None:
            raise FeishuError(AUTH, "USER_TOKEN_MISSING", "缺少用户访问凭证", retryable=False)
        meta = self.get_metadata(user_access_token, resource_token, resource_type)
        obj_token = meta.resource_token
        body = self._request(
            "GET", f"/open-apis/docx/v1/documents/{obj_token}/raw_content",
            token=user_access_token,
        )
        text = body.get("data", {}).get("content", "")
        return FeishuContent(
            title=meta.title,
            text=text,
            content_type=meta.resource_type,
            revision=meta.revision,
            modified_at=meta.modified_at,
            raw_payload={"document_id": obj_token, "raw_content": text},
        )


def _drive_file_to_document(f: dict[str, Any]) -> FeishuDocument:
    token = f.get("token", "")
    ftype = f.get("type", "file")
    return FeishuDocument(
        resource_token=token,
        canonical_token=token,
        title=f.get("name", ""),
        resource_type=_obj_type_to_resource_type(ftype),
        # drive 文件对象用 modified_time（秒级时间戳）
        modified_at=_parse_timestamp(f.get("modified_time") or f.get("modify_time")),
        owner_name=f.get("owner_id"),
        url=f.get("url"),
        extra={"parent_token": f.get("parent_token")},
    )


def _entity_to_document(entity: dict[str, Any]) -> FeishuDocument:
    token = entity.get("obj_token") or entity.get("token") or ""
    resource_type = _obj_type_to_resource_type(entity.get("obj_type"))
    return FeishuDocument(
        resource_token=token,
        canonical_token=token,
        title=entity.get("title", token),
        resource_type=resource_type,
        modified_at=_parse_timestamp(entity.get("modify_time") or entity.get("modified_time")),
        owner_name=entity.get("owner") or entity.get("owner_name"),
        url=entity.get("url"),
        extra={"node_token": entity.get("node_token")},
    )


def _obj_type_to_resource_type(obj_type: str | None) -> str:
    mapping = {"docx": "docx", "wiki": "wiki", "sheet": "sheet", "file": "file", "mindnote": "mindnote"}
    return mapping.get((obj_type or "").casefold(), (obj_type or "docx").casefold())


def _parse_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def _parse_url(url: str) -> tuple[str, str]:
    """从飞书 URL 提取 (token, resource_type)。"""
    lowered = url.casefold()
    for marker, resource_type in (("/wiki/", "wiki"), ("/docx/", "docx"), ("/sheets/", "sheet")):
        if marker in lowered:
            token = url.rsplit(marker, 1)[-1].split("?", 1)[0].rstrip("/")
            return token, resource_type
    raise FeishuError(VALIDATION, "UNSUPPORTED_URL", f"无法识别的飞书链接: {url}", retryable=False)
