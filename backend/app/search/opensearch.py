"""OpenSearch 检索引擎适配器（DD-19 §11.2，生产首选）。

- 走 REST API（httpx），不依赖 opensearchpy 客户端库；
- ensure_index：按需创建索引并应用版本化 mapping（填入实际向量维度）；
- bulk_index：`_bulk` 按 doc_id 覆盖写入（重跑幂等）；
- delete_generation：`_delete_by_query`（term 过滤 generation）；
- count_by_generation / get / sample：供 VERIFY 使用；
- 日志不含正文、向量、密钥。
"""

from __future__ import annotations

import base64
import json
import logging

import httpx

from .base import BulkIndexResult, SearchAdapterError
from .mapping import INDEX_MAPPING

logger = logging.getLogger(__name__)


class OpenSearchSearchAdapter:
    def __init__(
        self,
        *,
        base_url: str,
        index_name: str,
        username: str = "",
        password: str = "",
        http_client: httpx.Client | None = None,
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.index_name = index_name
        self.username = username
        self.password = password
        self.timeout = timeout
        self._http_client = http_client
        self._ensure_cache: set[str] = set()

    def _client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client(timeout=self.timeout)
        return self._http_client

    def _headers(self, *, json_body: bool = False) -> dict:
        headers = {}
        if self.username:
            token = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            headers["Authorization"] = f"Basic {token}"
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _request(self, method: str, path: str, *, json_body: dict | None = None) -> dict:
        resp = self._client().request(
            method,
            f"{self.base_url}/{path}",
            headers=self._headers(json_body=json_body is not None),
            json=json_body,
        )
        if resp.status_code in (401, 403):
            raise SearchAdapterError(
                "AUTH", "SEARCH_AUTH_FAILED", "检索引擎凭据无效", retryable=False, status=resp.status_code
            )
        if not 200 <= resp.status_code < 300:
            raise SearchAdapterError(
                "PROVIDER",
                f"SEARCH_{resp.status_code}",
                "检索引擎请求失败",
                retryable=resp.status_code >= 500,
                status=resp.status_code,
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise SearchAdapterError(
                "SCHEMA", "SEARCH_INVALID_JSON", "检索引擎返回非法 JSON", retryable=False
            ) from exc

    def ensure_index(self, dimension: int | None = None) -> None:
        """索引不存在时创建并应用版本化 mapping（缓存避免重复探测）。"""
        if self.index_name in self._ensure_cache:
            return
        head = self._client().head(f"{self.base_url}/{self.index_name}", headers=self._headers())
        if head.status_code not in (200, 404):
            if head.status_code in (401, 403):
                raise SearchAdapterError(
                    "AUTH", "SEARCH_AUTH_FAILED", "检索引擎凭据无效", retryable=False, status=head.status_code
                )
            raise SearchAdapterError(
                "PROVIDER", f"SEARCH_{head.status_code}", "检索引擎探测失败", retryable=True, status=head.status_code
            )
        if head.status_code == 404:
            mapping = json.loads(json.dumps(INDEX_MAPPING))
            if dimension:
                mapping["mappings"]["properties"]["embedding"]["dimension"] = dimension
            self._request("PUT", self.index_name, json_body=mapping)
        self._ensure_cache.add(self.index_name)

    def bulk_index(self, docs: list[dict], *, generation: str) -> BulkIndexResult:
        self.ensure_index(_detect_dimension(docs))
        lines: list[str] = []
        for doc in docs:
            did = doc.get("_id") or doc.get("doc_id")
            action = {"index": {"_index": self.index_name, "_id": did}}
            body = {k: v for k, v in doc.items() if k != "_id"}
            lines.append(json.dumps(action, ensure_ascii=False))
            lines.append(json.dumps(body, ensure_ascii=False))
        payload = ("\n".join(lines) + "\n").encode("utf-8")
        resp = self._client().post(
            f"{self.base_url}/{self.index_name}/_bulk",
            headers=self._headers(json_body=True),
            content=payload,
        )
        if not 200 <= resp.status_code < 300:
            raise SearchAdapterError(
                "PROVIDER",
                f"SEARCH_BULK_{resp.status_code}",
                "检索引擎批量写入失败",
                retryable=resp.status_code >= 500,
                status=resp.status_code,
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise SearchAdapterError(
                "SCHEMA", "SEARCH_INVALID_JSON", "检索引擎 bulk 返回非法 JSON", retryable=False
            ) from exc
        indexed = 0
        failed: list[str] = []
        for item in data.get("items", []):
            op = item.get("index") or {}
            status = op.get("status")
            if status is not None and 200 <= status < 300:
                indexed += 1
            else:
                failed.append(str(op.get("_id", "?")))
        return BulkIndexResult(indexed=indexed, failed=failed)

    def delete_generation(self, generation: str) -> int:
        body = {"query": {"term": {"generation": generation}}}
        data = self._request("POST", f"{self.index_name}/_delete_by_query", json_body=body)
        return int(data.get("deleted", 0))

    def count_by_generation(self, generation: str) -> int:
        body = {"query": {"term": {"generation": generation}}}
        data = self._request("POST", f"{self.index_name}/_count", json_body=body)
        return int(data.get("count", 0))

    def get(self, doc_id: str) -> dict | None:
        try:
            data = self._request("GET", f"{self.index_name}/_doc/{doc_id}")
        except SearchAdapterError as exc:
            if exc.status == 404:
                return None
            raise
        if not data.get("found"):
            return None
        source = dict(data.get("_source") or {})
        source["_id"] = doc_id
        return source

    def sample(self, generation: str, limit: int = 3) -> list[dict]:
        body = {"query": {"term": {"generation": generation}}, "size": limit}
        data = self._request("POST", f"{self.index_name}/_search", json_body=body)
        out: list[dict] = []
        for hit in data.get("hits", {}).get("hits", []):
            src = dict(hit.get("_source") or {})
            src["_id"] = hit.get("_id")
            out.append(src)
        return out

    def health(self) -> bool:
        try:
            data = self._request("GET", "_cluster/health")
            return str(data.get("status")) in ("green", "yellow")
        except SearchAdapterError:
            return False


def _detect_dimension(docs: list[dict]) -> int | None:
    for doc in docs:
        emb = doc.get("embedding")
        if isinstance(emb, list):
            return len(emb)
    return None
