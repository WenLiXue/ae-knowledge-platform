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


# ---- Fake search()（Phase 5 检索）----

def _search_doc(cid: str, gen: str, version_id: str, content: str, *, title: str = "", heading=None) -> dict:
    doc = _doc(cid, gen, content=content)
    doc.update(
        {"version_id": version_id, "title": title, "heading_path": heading or [], "source_id": "src-1"}
    )
    return doc


def test_fake_search_bm25_ranks_and_filters() -> None:
    adapter = FakeSearchAdapter()
    adapter.bulk_index(
        [
            _search_doc("c1", "g1", "v1", "E3800 防病毒吞吐量 3.5G 内存 64G"),
            _search_doc("c2", "g1", "v1", "信舷防毒墙 网桥模式 路由模式"),
            _search_doc("c3", "g2", "v2", "E3800 吞吐量 与内存的规格"),
        ],
        generation="g1",
    )
    res = adapter.search(query_text="E3800 内存", retrieval_type="bm25", top_k=10, version_ids=["v1"])
    # 无匹配词的文档分数为 0 被过滤；预过滤生效，只返回 v1 中命中者
    assert res.total == 1
    assert res.hits[0]["chunk_id"] == "c1"  # 完全命中 E3800+内存
    assert all(hit["version_id"] == "v1" for hit in res.hits)
    # 无 version 过滤则包含 v2（c3 也含 E3800）
    res2 = adapter.search(query_text="E3800", retrieval_type="bm25", top_k=10)
    assert {h["chunk_id"] for h in res2.hits} == {"c1", "c3"}


def test_fake_search_vector_cosine() -> None:
    adapter = FakeSearchAdapter()
    c1 = _search_doc("c1", "g1", "v1", "苹果 香蕉")
    c1["embedding"] = _token_vector("苹果 香蕉")
    c2 = _search_doc("c2", "g1", "v1", "香蕉 葡萄")
    c2["embedding"] = _token_vector("香蕉 葡萄")
    adapter.bulk_index([c1, c2], generation="g1")
    # 构造与 c1 共享 token 的查询向量，余弦应把 c1 排最前
    query_vec = _token_vector("苹果")
    res = adapter.search(embedding=query_vec, retrieval_type="vector", top_k=5)
    assert res.hits[0]["chunk_id"] == "c1"


def _token_vector(text: str) -> list[float]:
    import hashlib

    vec = [0.0] * 8
    from app.search.bm25 import tokenize

    for token in tokenize(text):
        idx = hashlib.sha256(token.encode("utf-8")).digest()[0] % 8
        vec[idx] += 1.0
    return vec


def test_fake_search_unknown_type_raises() -> None:
    adapter = FakeSearchAdapter()
    adapter.bulk_index([_search_doc("c1", "g1", "v1", "正文")], generation="g1")
    import pytest

    with pytest.raises(ValueError):
        adapter.search(query_text="x", retrieval_type="hybrid", top_k=5)


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


# ---- OpenSearch search()（Phase 5 检索）----

def _search_handler(seen: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200, json={})
        if request.url.path.endswith("/_search"):
            seen.append(json.loads(request.content.decode()))
            return httpx.Response(
                200,
                json={
                    "hits": {
                        "total": {"value": 1, "relation": "eq"},
                        "hits": [
                            {
                                "_id": "chunk:c1:gen:g",
                                "_score": 3.2,
                                "_source": {"content": "正文", "chunk_id": "c1", "generation": "g", "version_id": "v1"},
                            }
                        ],
                    }
                },
            )
        return httpx.Response(404, json={})

    return handler


def test_opensearch_search_bm25_request_shape() -> None:
    seen: list[dict] = []
    adapter = _opensearch(_search_handler(seen))
    res = adapter.search(query_text="E3800", retrieval_type="bm25", top_k=50, version_ids=["v1"])

    assert res.total == 1
    assert res.hits[0]["_id"] == "chunk:c1:gen:g"
    assert res.hits[0]["_score"] == 3.2
    body = seen[0]
    assert body["size"] == 50
    assert body["query"]["bool"]["filter"] == [{"terms": {"version_id": ["v1"]}}]
    must = body["query"]["bool"]["must"][0]
    assert must["multi_match"]["query"] == "E3800"
    assert must["multi_match"]["fields"] == ["title^2", "heading_path^1.5", "content"]


def test_opensearch_search_vector_request_shape() -> None:
    seen: list[dict] = []
    adapter = _opensearch(_search_handler(seen))
    res = adapter.search(embedding=[0.1, 0.2], retrieval_type="vector", top_k=12)

    assert res.total == 1
    body = seen[0]
    # 无 version 过滤时 query 直接为 knn（无 bool 包装、无 filter）
    knn = body["query"]["knn"]
    assert knn["embedding"]["vector"] == [0.1, 0.2]
    assert knn["embedding"]["k"] == 12
    assert "bool" not in body["query"]
