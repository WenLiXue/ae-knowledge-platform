"""检索引擎适配器测试（DD-19 §11.2）。

覆盖：FakeSearchAdapter 的 bulk/按 generation 过滤计数/按 ID 读取/删除 generation；
OpenSearchSearchAdapter 经 httpx.MockTransport 的请求路径与请求体形状（_bulk ndjson、
_delete_by_query、_count、_doc/{id}、_search、_cluster/health）及错误映射。
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.search.base import BulkIndexResult, SearchAdapterError
from app.search.fake import FakeSearchAdapter
from app.search.mapping import doc_id
from app.search.opensearch import OpenSearchSearchAdapter


def _doc(chunk_id: str, generation: str, content: str = "正文") -> dict:
    return {
        "_id": doc_id(chunk_id, generation),
        "chunk_id": chunk_id,
        "generation": generation,
        "content": content,
        "embedding": [0.1, 0.2, 0.3],
        "ordinal": 1,
    }


# ---- Fake ----

def test_fake_bulk_index_and_count() -> None:
    adapter = FakeSearchAdapter()
    gen = "gen-1"
    result = adapter.bulk_index([_doc("c1", gen), _doc("c2", gen), _doc("c3", gen)], generation=gen)
    assert isinstance(result, BulkIndexResult)
    assert result.indexed == 3 and result.failed == []
    assert adapter.count_by_generation(gen) == 3
    # 覆盖写入幂等：相同 doc_id 重写不追加
    adapter.bulk_index([_doc("c1", gen, content="新内容")], generation=gen)
    assert adapter.count_by_generation(gen) == 3
    assert adapter.get(doc_id("c1", gen))["content"] == "新内容"


def test_fake_delete_generation() -> None:
    adapter = FakeSearchAdapter()
    g1, g2 = "gen-1", "gen-2"
    adapter.bulk_index([_doc("a", g1), _doc("b", g1)], generation=g1)
    adapter.bulk_index([_doc("c", g2)], generation=g2)
    assert adapter.delete_generation(g1) == 2
    assert adapter.count_by_generation(g1) == 0
    assert adapter.count_by_generation(g2) == 1
    assert adapter.get(doc_id("a", g1)) is None


def test_fake_sample_and_bulk_failures() -> None:
    adapter = FakeSearchAdapter()
    gen = "gen-1"
    adapter.fail_bulk.add(doc_id("bad", gen))
    result = adapter.bulk_index([_doc("ok", gen), _doc("bad", gen)], generation=gen)
    assert result.indexed == 1 and result.failed == [doc_id("bad", gen)]
    assert adapter.count_by_generation(gen) == 1
    sample = adapter.sample(gen, limit=10)
    assert len(sample) == 1 and sample[0]["chunk_id"] == "ok"
    assert adapter.health() is True


# ---- OpenSearch（MockTransport）----

def _opensearch(handler) -> OpenSearchSearchAdapter:
    return OpenSearchSearchAdapter(
        base_url="http://os.test.local:9200",
        index_name="knowledge_chunks",
        username="u",
        password="p",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_opensearch_bulk_index_request_shape() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "HEAD":
            return httpx.Response(404)  # 索引不存在 → 创建
        if request.method == "PUT" and request.url.path == "/knowledge_chunks":
            return httpx.Response(200, json={"acknowledged": True})
        if request.method == "POST" and request.url.path.endswith("/_bulk"):
            return httpx.Response(200, json={"items": [{"index": {"status": 201}}, {"index": {"status": 201}}]})
        return httpx.Response(404, json={})

    adapter = _opensearch(handler)
    gen = "gen-x"
    result = adapter.bulk_index([_doc("c1", gen), _doc("c2", gen)], generation=gen)

    assert result.indexed == 2 and result.failed == []
    paths = [r.url.path for r in requests]
    assert "/knowledge_chunks" in paths          # PUT 建索引
    assert paths[-1].endswith("/_bulk")          # 最后是 bulk
    bulk_body = requests[-1].content.decode("utf-8")
    lines = bulk_body.strip().splitlines()
    assert len(lines) == 4  # 2 动作 + 2 文档体
    action = json.loads(lines[0])
    assert action["index"]["_index"] == "knowledge_chunks"
    assert action["index"]["_id"] == doc_id("c1", gen)
    body = json.loads(lines[1])
    assert body["content"] == "正文" and body["generation"] == gen


def test_opensearch_bulk_reports_failed_items() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200, json={})
        if request.method == "POST" and request.url.path.endswith("/_bulk"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"index": {"status": 201, "_id": "ok"}},
                        {"index": {"status": 400, "_id": "bad"}},
                    ]
                },
            )
        return httpx.Response(200, json={})

    adapter = _opensearch(handler)
    result = adapter.bulk_index([_doc("a", "g"), _doc("b", "g")], generation="g")
    assert result.indexed == 1 and result.failed == ["bad"]


def test_opensearch_count_delete_get_sample_and_health() -> None:
    seen: list[tuple[str, str, dict | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/_cluster/health":
            return httpx.Response(200, json={"status": "green"})
        if request.url.path.endswith("/_count"):
            seen.append(("count", request.url.path, request.content))
            return httpx.Response(200, json={"count": 2})
        if request.url.path.endswith("/_delete_by_query"):
            seen.append(("delete", request.url.path, request.content))
            return httpx.Response(200, json={"deleted": 2})
        if request.url.path.endswith("/_search"):
            seen.append(("search", request.url.path, request.content))
            return httpx.Response(
                200,
                json={
                    "hits": {
                        "hits": [
                            {
                                "_id": "chunk:c1:generation:g",
                                "_source": {"content": "a", "generation": "g", "chunk_id": "c1"},
                            }
                        ]
                    }
                },
            )
        if "_doc/" in request.url.path:
            seen.append(("get", request.url.path, None))
            return httpx.Response(
                200, json={"found": True, "_source": {"content": "a", "generation": "g", "chunk_id": "c1"}}
            )
        return httpx.Response(200, json={})

    adapter = _opensearch(handler)
    assert adapter.health() is True
    assert adapter.count_by_generation("g") == 2
    assert adapter.delete_generation("g") == 2
    got = adapter.get("chunk:c1:generation:g")
    assert got and got["content"] == "a"
    assert adapter.sample("g")[0]["chunk_id"] == "c1"

    paths = [p for method, p, _ in seen]
    assert any(p.endswith("/_count") for p in paths)
    assert any(p.endswith("/_delete_by_query") for p in paths)
    assert any(p.endswith("/_search") for p in paths)
    assert any("_doc/" in p for p in paths)
    # 过滤查询按 generation term 构造
    count_body = next(b for m, _, b in seen if m == "count").decode()
    assert '"term"' in count_body and '"generation"' in count_body


def test_opensearch_auth_and_5xx_error_mapping() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/_cluster/health":
            return httpx.Response(401, json={})
        return httpx.Response(503, json={})

    adapter = _opensearch(handler)
    # count 命中 503 → PROVIDER 可重试；health 命中 401 → AUTH 不可重试（health 吞错返回 False）
    with pytest.raises(SearchAdapterError) as exc:
        adapter.count_by_generation("g")
    assert exc.value.category == "PROVIDER" and exc.value.retryable is True
    assert adapter.health() is False
