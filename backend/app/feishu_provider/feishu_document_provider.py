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
from urllib.parse import parse_qs, quote, urlparse

import httpx

from ..core.logging import log_external_call
from ..parsing.files import extract_file_text
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
            if resp.status_code == 401:
                result = "auth_expired"
                raise FeishuError(AUTH, "FEISHU_AUTH_EXPIRED", "飞书授权失效", retryable=False)
            if resp.status_code == 403:
                result = "permission_denied"
                raise FeishuError(PERMISSION, "FEISHU_PERMISSION_DENIED", "无权访问该飞书资源", retryable=False)
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
                json={"search_key": query, "count": limit, **({"page_token": page_token} if page_token else {})},
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
        document = self.get_metadata(user_access_token, token, resource_type)
        document.url = url
        selected_sheet_id = _selected_sheet_id(url)
        if selected_sheet_id:
            document.extra["selected_sheet_id"] = selected_sheet_id
            if document.resource_type == "sheet":
                document.canonical_token = f"{document.resource_token}#{selected_sheet_id}"
        return document

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
        if resource_type == "sheet":
            body = self._request(
                "GET", f"/open-apis/sheets/v3/spreadsheets/{resource_token}",
                token=user_access_token,
            )
            spreadsheet = body.get("data", {}).get("spreadsheet", {})
            return FeishuDocument(
                resource_token=resource_token,
                canonical_token=resource_token,
                title=spreadsheet.get("title", resource_token),
                resource_type="sheet",
                owner_name=spreadsheet.get("owner_id"),
                url=spreadsheet.get("url"),
            )
        if resource_type == "file":
            body = self._request(
                "GET", f"/open-apis/drive/v1/files/{resource_token}", token=user_access_token,
            )
            file_meta = body.get("data", {}).get("file", {}) or body.get("data", {})
            return FeishuDocument(
                resource_token=resource_token,
                canonical_token=resource_token,
                title=file_meta.get("name", resource_token),
                resource_type="file",
                modified_at=_parse_timestamp(file_meta.get("modified_time") or file_meta.get("modify_time")),
                owner_name=file_meta.get("owner_id"),
                url=file_meta.get("url"),
                extra={"file_type": file_meta.get("type"), "size": file_meta.get("size")},
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
        self,
        user_access_token: str | None,
        resource_token: str,
        resource_type: str,
        *,
        source_url: str | None = None,
    ) -> FeishuContent:
        if user_access_token is None:
            raise FeishuError(AUTH, "USER_TOKEN_MISSING", "缺少用户访问凭证", retryable=False)
        meta = self.get_metadata(user_access_token, resource_token, resource_type)
        obj_token = meta.resource_token
        if meta.resource_type == "sheet":
            return self._fetch_sheet(
                user_access_token,
                obj_token,
                meta,
                source_url=source_url,
            )
        if meta.resource_type == "file":
            data = self._download_file(user_access_token, obj_token)
            filename = meta.title or obj_token
            try:
                text = extract_file_text(filename, data)
            except ValueError as exc:
                raise FeishuError(VALIDATION, "UNSUPPORTED_FILE_TYPE", "飞书附件仅支持 PDF、DOCX 和 XLSX", retryable=False) from exc
            except Exception as exc:
                raise FeishuError(VALIDATION, "FILE_PARSE_FAILED", "无法解析飞书附件", retryable=False) from exc
            return FeishuContent(
                title=meta.title,
                text=text,
                content_type="file",
                revision=meta.revision,
                modified_at=meta.modified_at,
                raw_payload={"type": "file", "filename": filename, "raw_content": text},
                raw_bytes=data,
                filename=filename,
            )
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

    def _download_file(self, user_access_token: str, file_token: str) -> bytes:
        """下载云空间附件；该接口返回二进制流，不经过 JSON _request。"""
        path = f"/open-apis/drive/v1/files/{file_token}/download"
        headers = {"Authorization": f"Bearer {user_access_token}"}
        try:
            resp = self._http.get(f"{self._base_url}{path}", headers=headers)
        except httpx.TimeoutException as exc:
            raise FeishuError(TIMEOUT, "FEISHU_TIMEOUT", "飞书附件下载超时", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise FeishuError(TRANSIENT, "FEISHU_NETWORK", "飞书附件下载失败", retryable=True) from exc
        if resp.status_code == 401:
            raise FeishuError(AUTH, "FEISHU_AUTH_EXPIRED", "飞书授权失效", retryable=False)
        if resp.status_code == 403:
            raise FeishuError(PERMISSION, "FEISHU_PERMISSION_DENIED", "无权下载该飞书附件", retryable=False)
        if resp.status_code == 404:
            raise FeishuError(NOT_FOUND, "DOC_NOT_FOUND", "飞书附件不存在", retryable=False)
        if resp.status_code == 429:
            raise FeishuError(RATE_LIMIT, "FEISHU_RATE_LIMITED", "飞书接口限流", retryable=True)
        if resp.status_code >= 500:
            raise FeishuError(TRANSIENT, "FEISHU_DOWNLOAD_FAILED", "飞书附件服务暂时不可用", retryable=True)
        if resp.status_code != 200:
            raise FeishuError(VALIDATION, "FEISHU_DOWNLOAD_FAILED", "飞书附件下载失败", retryable=False)
        return resp.content

    def _fetch_sheet(
        self,
        user_access_token: str,
        spreadsheet_token: str,
        meta: FeishuDocument,
        *,
        source_url: str | None,
    ) -> FeishuContent:
        body = self._request(
            "GET",
            f"/open-apis/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/query",
            token=user_access_token,
        )
        sheets = body.get("data", {}).get("sheets", []) or []
        selected_sheet_id = _selected_sheet_id(source_url)
        if selected_sheet_id:
            sheets = [sheet for sheet in sheets if str(sheet.get("sheet_id")) == selected_sheet_id]
            if not sheets:
                raise FeishuError(
                    NOT_FOUND,
                    "SHEET_NOT_FOUND",
                    "链接中指定的工作表不存在或当前用户无权访问",
                    retryable=False,
                )
        else:
            sheets = [sheet for sheet in sheets if not sheet.get("hidden", False)]

        remaining_cells = 100_000
        revision: str | None = None
        payload_sheets: list[dict[str, Any]] = []
        text_parts: list[str] = []
        for sheet in sheets:
            if remaining_cells <= 0:
                break
            sheet_id = str(sheet.get("sheet_id") or "")
            if not sheet_id:
                continue
            grid = sheet.get("grid_properties") or {}
            column_count = max(1, min(int(grid.get("column_count") or 1), 100))
            row_count = max(1, int(grid.get("row_count") or 1))
            row_count = min(row_count, max(1, remaining_cells // column_count))
            cell_range = f"{sheet_id}!A1:{_column_name(column_count)}{row_count}"
            value_body = self._request(
                "GET",
                f"/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/values/{quote(cell_range, safe='!:')}",
                token=user_access_token,
                params={
                    "valueRenderOption": "FormattedValue",
                    "dateTimeRenderOption": "FormattedString",
                    "user_id_type": "open_id",
                },
            )
            data = value_body.get("data", {})
            value_range = data.get("valueRange", {}) or {}
            values = _trim_sheet_values(value_range.get("values") or [])
            current_revision = data.get("revision", value_range.get("revision"))
            if current_revision is not None:
                revision = str(current_revision)
            if not values:
                continue
            actual_range = _actual_range(sheet_id, values)
            sheet_title = str(sheet.get("title") or sheet_id)
            payload_sheets.append(
                {
                    "sheet_id": sheet_id,
                    "title": sheet_title,
                    "range": actual_range,
                    "values": values,
                }
            )
            text_parts.append(sheet_title)
            text_parts.extend("\t".join(_cell_text(cell) for cell in row) for row in values)
            remaining_cells -= sum(len(row) for row in values)

        raw_payload = {
            "type": "sheet",
            "spreadsheet_token": spreadsheet_token,
            "title": meta.title,
            "source_url": source_url or meta.url,
            "sheets": payload_sheets,
            "truncated": remaining_cells <= 0,
        }
        return FeishuContent(
            title=meta.title,
            text="\n".join(text_parts),
            content_type="sheet",
            revision=revision,
            modified_at=meta.modified_at,
            raw_payload=raw_payload,
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
    # Wiki 节点接口在不同租户/版本可能返回 doc、docx、sheet 或 spreadsheet；
    # 统一映射到提交接口支持的资源类型。
    mapping = {
        "doc": "docx",
        "docx": "docx",
        "document": "docx",
        "wiki": "wiki",
        "sheet": "sheet",
        "spreadsheet": "sheet",
        "file": "file",
        "mindnote": "mindnote",
    }
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


def _selected_sheet_id(url: str | None) -> str | None:
    if not url:
        return None
    values = parse_qs(urlparse(url).query).get("sheet") or []
    value = values[0].strip() if values else ""
    return value or None


def _column_name(column_count: int) -> str:
    value = column_count
    chars: list[str] = []
    while value:
        value, remainder = divmod(value - 1, 26)
        chars.append(chr(ord("A") + remainder))
    return "".join(reversed(chars))


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return str(value.get("text") or value.get("link") or value)
    return str(value)


def _trim_sheet_values(raw_values: list[Any]) -> list[list[str]]:
    rows = [
        [_cell_text(cell).strip() for cell in row] if isinstance(row, list) else []
        for row in raw_values
    ]
    while rows and not any(rows[-1]):
        rows.pop()
    if not rows:
        return []
    last_column = max((index for row in rows for index, value in enumerate(row) if value), default=-1)
    if last_column < 0:
        return []
    return [(row + [""] * (last_column + 1 - len(row)))[: last_column + 1] for row in rows]


def _actual_range(sheet_id: str, values: list[list[str]]) -> str:
    return f"{sheet_id}!A1:{_column_name(max(len(row) for row in values))}{len(values)}"
