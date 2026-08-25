"""真实 CHUNK/EMBED/INDEX/VERIFY/FINALIZE 流水线集成测试（DD-19 §10-§11，Phase 4）。

覆盖（feature_real_indexing=True）：
- 全路径：相关文档 → 切片落库 → 向量化 → 索引 → VERIFY → QUERYABLE，索引文档带元数据；
- 幂等：重跑 CHUNK 不追加重复切片，ordinal 唯一；
- Embedding 模型未配置：禁止入索引，任务 FAILED；
- Embedding 数量不匹配：禁止入索引；
- 索引 VERIFY 数量不一致：不进入 QUERYABLE；
- 新版激活：旧版 SUPERSEDED、旧 generation 异步清理。

模型调用注入 Fake 网关（monkeypatch pipeline.create_gateway）；检索引擎用 FakeSearchAdapter 注入 Worker。
"""

from __future__ import annotations

import json
import tempfile
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.main import app
from app.model_gateway.base import (
    ChatResponse,
    ChatUsage,
    EmbeddingData,
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingUsage,
)
from app.search.fake import FakeSearchAdapter
from app.storage.local import LocalObjectStore
from app.worker.runner import WorkerRunner

client = TestClient(app)

_SYSTEM_USER_ID = "11111111-1111-1111-1111-111111111111"

BASELINE_DOCUMENT_TYPES = [
    ("product-spec", "产品规格", 10),
    ("product-whitepaper", "产品白皮书", 20),
    ("requirement", "需求说明书", 30),
    ("design", "设计文档", 40),
    ("deployment-guide", "部署说明", 50),
    ("operation-manual", "操作手册", 60),
    ("test-report", "测试报告", 70),
    ("fault-analysis", "故障分析", 80),
    ("seg-case", "SEG 问题案件", 90),
    ("compatibility-list", "兼容性清单", 100),
    ("release-note", "版本说明", 110),
    ("other", "其他资料", 999),
]


def _relevant_output() -> dict:
    return {
        "relevance": "RELEVANT",
        "relevance_confidence": 0.95,
        "product_code": "TDA",
        "product_version_code": "7.0.3",
        "document_type_code": "deployment-guide",
        "product_form_code": None,
        "is_domestic": None,
        "module_name": None,
        "business_topic": "硬件部署",
        "keywords": ["部署", "TDA"],
        "summary": "TDA 7.0.3 部署文档",
        "field_confidence": {"document_type": 0.9},
        "evidence": [{"field": "relevance", "locator_ids": ["title"], "excerpts": ["TDA"]}],
        "missing_fields": [],
        "reason_summary": "标题与正文涉及 TDA 部署",
    }


class FakeEmbeddingGateway:
    """确定性假向量网关。可注入返回数量异常（count_offset）。"""

    def __init__(self, dim: int = 8, count_offset: int = 0):
        self.dim = dim
        self.count_offset = count_offset

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        data = [
            EmbeddingData(index=i, embedding=[float(i + 1) / 10.0 for _ in range(self.dim)])
            for i in range(len(request.input))
        ]
        if self.count_offset > 0:
            data = data[: max(0, len(data) - self.count_offset)]
        return EmbeddingResponse(model=request.model, data=data, usage=EmbeddingUsage(total_tokens=len(request.input)))


class FakeCombinedGateway:
    """分类（chat）+ 向量化（embed）一体的假网关。"""

    def chat(self, request):
        return ChatResponse(
            model=request.model,
            content=json.dumps(_relevant_output()),
            usage=ChatUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        data = [
            EmbeddingData(index=i, embedding=[float(i + 1) / 10.0 for _ in range(8)])
            for i in range(len(request.input))
        ]
        return EmbeddingResponse(model=request.model, data=data, usage=EmbeddingUsage(total_tokens=len(request.input)))


class _ShortCountAdapter(FakeSearchAdapter):
    """VERIFY 失败注入：count_by_generation 永远少 1。"""

    def count_by_generation(self, generation: str) -> int:
        return max(0, super().count_by_generation(generation) - 1)


# ---- 基础设施 ----

def _seed_catalog() -> None:
    from app.db.models.catalog import DocumentType, Product, ProductVersion

    with SessionLocal() as s:
        for code, name, sort_order in BASELINE_DOCUMENT_TYPES:
            s.add(DocumentType(code=code, name=name, sort_order=sort_order))
        product = Product(code="TDA", name="TDA")
        s.add(product)
        s.flush()
        s.add(ProductVersion(product_id=product.id, version_code="7.0.3", sort_order=0))
        s.commit()


def _seed_llm_models(*, classify: bool, embed: bool) -> None:
    from app.llm import service as llm_service
    from app.llm.schemas import LlmModelCreate, ServiceBindingsUpdate

    with SessionLocal() as s:
        binds = {
            "QA": None,
            "DOCUMENT_CLASSIFICATION": None,
            "DOCUMENT_EMBEDDING": None,
            "RETRIEVAL_RERANK": None,
        }
        if classify:
            model = llm_service.create_model(
                s,
                LlmModelCreate(
                    name="分类模型",
                    model_type="CHAT",
                    provider="openai-compatible",
                    base_url="https://llm.test.local/v1",
                    model_name="test-classifier",
                    api_key="sk-test",
                ),
                user_id=_SYSTEM_USER_ID,
            )
            binds["DOCUMENT_CLASSIFICATION"] = model["id"]
        if embed:
            model = llm_service.create_model(
                s,
                LlmModelCreate(
                    name="向量模型",
                    model_type="EMBEDDING",
                    provider="openai-compatible",
                    base_url="https://llm.test.local/v1",
                    model_name="test-embedder",
                    api_key="sk-test",
                ),
                user_id=_SYSTEM_USER_ID,
            )
            binds["DOCUMENT_EMBEDDING"] = model["id"]
        revision = llm_service.list_models(s)["revision"]
        llm_service.update_service_bindings(
            s,
            ServiceBindingsUpdate(expected_revision=revision, bindings=binds),
            user_id=_SYSTEM_USER_ID,
        )
        s.commit()


def _submit(token: str) -> dict:
    response = client.post(
        "/api/v1/feishu/documents/submit",
        json={"items": [{"client_item_id": "row-1", "resource_token": token, "resource_type": "wiki"}]},
    )
    assert response.status_code == 202, response.text
    return response.json()["data"]["items"][0]


def _runner(search=None) -> WorkerRunner:
    return WorkerRunner(
        worker_id="test-worker",
        retry_base_delay_seconds=0.0,
        lease_seconds=60,
        store=LocalObjectStore(tempfile.mkdtemp(prefix="ae-idx-test-storage-")),
        search=search or FakeSearchAdapter(),
    )


def _drain(runner: WorkerRunner, max_cycles: int = 40) -> None:
    for _ in range(max_cycles):
        runner.claim_and_execute(batch_size=10)
        with SessionLocal() as session:
            open_tasks = session.execute(
                text(
                    "SELECT count(*) FROM tasking.processing_tasks "
                    "WHERE status IN ('PENDING', 'RUNNING', 'RETRY_WAIT')"
                )
            ).scalar_one()
        if open_tasks == 0:
            return
    raise AssertionError("Worker 未在预期轮次内排空任务")


def _scalar(sql: str, **params):
    with SessionLocal() as session:
        return session.execute(text(sql), params).scalar_one()


@pytest.fixture()
def real_indexing(monkeypatch):
    """开启真实索引开关，并把 create_gateway 注入假向量网关。"""
    monkeypatch.setattr(get_settings(), "feature_real_indexing", True)
    import app.worker.pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module, "create_gateway", lambda resolved: FakeEmbeddingGateway())
    yield


@pytest.fixture()
def real_all(monkeypatch):
    """真实分类 + 真实索引（组合网关）。"""
    monkeypatch.setattr(get_settings(), "feature_real_classification", True)
    monkeypatch.setattr(get_settings(), "feature_real_indexing", True)
    import app.worker.pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module, "create_gateway", lambda resolved: FakeCombinedGateway())
    yield


# ---- 测试 ----

def test_real_indexing_full_path_relevant_queryable_with_metadata(real_all) -> None:
    _seed_catalog()
    _seed_llm_models(classify=True, embed=True)
    adapter = FakeSearchAdapter()
    submitted = _submit("docx-product-whitepaper")
    _drain(_runner(search=adapter))

    assert (
        _scalar("SELECT status FROM knowledge.knowledge_sources WHERE id=:sid", sid=submitted["source_id"])
        == "QUERYABLE"
    )
    assert (
        _scalar("SELECT status FROM knowledge.document_versions WHERE id=:vid", vid=submitted["version_id"])
        == "READY"
    )
    # 切片落库且字段完整
    chunk_rows = _scalar(
        "SELECT count(*) FROM knowledge.document_chunks WHERE version_id=:vid", vid=submitted["version_id"]
    )
    assert chunk_rows > 0
    with SessionLocal() as session:
        chunk = session.execute(
            text(
                "SELECT content_sha256, locator_json, metadata_snapshot FROM knowledge.document_chunks "
                "WHERE version_id=:vid ORDER BY ordinal LIMIT 1"
            ),
            {"vid": submitted["version_id"]},
        ).one()
    assert len(chunk.content_sha256) == 64
    assert chunk.locator_json["element_ids"]
    assert chunk.metadata_snapshot["product_code"] == "TDA"
    assert chunk.metadata_snapshot["document_type_code"] == "deployment-guide"

    # 索引 generation 写入，索引文档数量 == DB chunk 数，且带过滤元数据
    generation = _scalar(
        "SELECT index_generation FROM knowledge.document_versions WHERE id=:vid", vid=submitted["version_id"]
    )
    assert generation is not None
    assert adapter.count_by_generation(generation) == chunk_rows
    docs = adapter.sample(generation, limit=10)
    assert docs and docs[0]["product_code"] == "TDA"
    assert docs[0]["document_type_code"] == "deployment-guide"
    assert len(docs[0]["embedding"]) == 8
    assert _scalar(
        "SELECT embedding_dimension FROM knowledge.document_versions WHERE id=:vid", vid=submitted["version_id"]
    ) == 8


def test_real_indexing_idempotent_rerun_no_duplicate_chunks(real_indexing) -> None:
    from app.db.models.task import ProcessingTask

    _seed_llm_models(classify=False, embed=True)
    adapter = FakeSearchAdapter()
    submitted = _submit("docx-product-whitepaper")
    _drain(_runner(search=adapter))

    assert (
        _scalar("SELECT status FROM knowledge.knowledge_sources WHERE id=:sid", sid=submitted["source_id"])
        == "QUERYABLE"
    )
    before = _scalar(
        "SELECT count(*) FROM knowledge.document_chunks WHERE version_id=:vid", vid=submitted["version_id"]
    )
    assert before == 1

    # 手动重排 CHUNK：替换式写入，不追加
    with SessionLocal() as session:
        session.add(
            ProcessingTask(
                task_type="CHUNK",
                status="PENDING",
                idempotency_key=f"version:{submitted['version_id']}:stage:chunk:manual",
                scheduled_at=datetime.now(timezone.utc),
                source_id=uuid.UUID(submitted["source_id"]),
                version_id=uuid.UUID(submitted["version_id"]),
                priority=100,
                max_attempts=3,
            )
        )
        session.commit()
    _drain(_runner(search=adapter))

    after = _scalar(
        "SELECT count(*) FROM knowledge.document_chunks WHERE version_id=:vid", vid=submitted["version_id"]
    )
    assert after == before
    # ordinal 唯一连续
    with SessionLocal() as session:
        ordinals = [r[0] for r in session.execute(
            text("SELECT ordinal FROM knowledge.document_chunks WHERE version_id=:vid ORDER BY ordinal"),
            {"vid": submitted["version_id"]},
        )]
    assert ordinals == list(range(1, after + 1))


def test_real_indexing_embedding_model_missing_fails(real_indexing) -> None:
    # 不配置 DOCUMENT_EMBEDDING：禁止入索引
    submitted = _submit("docx-product-whitepaper")
    _drain(_runner(search=FakeSearchAdapter()))

    assert (
        _scalar("SELECT status FROM knowledge.knowledge_sources WHERE id=:sid", sid=submitted["source_id"])
        == "FAILED"
    )
    assert (
        _scalar(
            "SELECT last_error_code FROM tasking.processing_tasks WHERE version_id=:vid AND task_type='EMBED'",
            vid=submitted["version_id"],
        )
        == "REQUIRED_SERVICE_MODEL_MISSING"
    )
    assert _scalar(
        "SELECT index_generation FROM knowledge.document_versions WHERE id=:vid", vid=submitted["version_id"]
    ) is None


def test_real_indexing_embedding_count_mismatch_blocks_index(real_indexing, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "feature_real_indexing", True)
    import app.worker.pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module, "create_gateway", lambda resolved: FakeEmbeddingGateway(count_offset=1))
    _seed_llm_models(classify=False, embed=True)
    adapter = FakeSearchAdapter()
    submitted = _submit("docx-product-whitepaper")
    _drain(_runner(search=adapter))

    assert (
        _scalar("SELECT status FROM knowledge.knowledge_sources WHERE id=:sid", sid=submitted["source_id"])
        == "FAILED"
    )
    assert _scalar(
        "SELECT index_generation FROM knowledge.document_versions WHERE id=:vid", vid=submitted["version_id"]
    ) is None
    assert len(adapter._by_generation) == 0


def test_real_indexing_verify_mismatch_blocks_queryable(real_indexing, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "feature_real_indexing", True)
    import app.worker.pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module, "create_gateway", lambda resolved: FakeEmbeddingGateway())
    _seed_llm_models(classify=False, embed=True)
    submitted = _submit("docx-product-whitepaper")
    _drain(_runner(search=_ShortCountAdapter()))

    # 索引数量校验失败 → 不进入 QUERYABLE，index_generation 不提交
    assert (
        _scalar("SELECT status FROM knowledge.knowledge_sources WHERE id=:sid", sid=submitted["source_id"])
        != "QUERYABLE"
    )
    assert _scalar(
        "SELECT index_generation FROM knowledge.document_versions WHERE id=:vid", vid=submitted["version_id"]
    ) is None


def test_real_indexing_new_version_supersedes_and_cleans_old_generation(real_indexing) -> None:
    from app.db.models.knowledge import DocumentVersion
    from app.db.models.task import ProcessingTask

    _seed_llm_models(classify=False, embed=True)
    adapter = FakeSearchAdapter()
    submitted = _submit("docx-product-whitepaper")
    _drain(_runner(search=adapter))
    source_id = submitted["source_id"]
    v1 = submitted["version_id"]
    gen1 = _scalar("SELECT index_generation FROM knowledge.document_versions WHERE id=:vid", vid=v1)
    assert gen1 is not None
    assert adapter.count_by_generation(gen1) > 0

    # 模拟第二版已索引完成：直接建 version_no=2 + FINALIZE 任务
    v2 = uuid.uuid4()
    with SessionLocal() as session:
        session.add(
            DocumentVersion(
                id=v2,
                source_id=uuid.UUID(source_id),
                version_no=2,
                status="PROCESSING",
                external_revision="rev-2",
                index_generation=f"gen-{v2}",
            )
        )
        session.flush()  # 先让 v2 落库，避免 pending_version_id 外键引用尚未插入的行
        session.execute(
            text("UPDATE knowledge.knowledge_sources SET pending_version_id=:v2 WHERE id=:sid"),
            {"v2": v2, "sid": uuid.UUID(source_id)},
        )
        session.add(
            ProcessingTask(
                task_type="FINALIZE",
                status="PENDING",
                idempotency_key=f"version:{v2}:stage:finalize",
                scheduled_at=datetime.now(timezone.utc),
                source_id=uuid.UUID(source_id),
                version_id=v2,
                priority=100,
                max_attempts=3,
            )
        )
        session.commit()
    _drain(_runner(search=adapter))

    # 新版激活，旧版 SUPERSEDED，旧 generation 已清理
    assert _scalar("SELECT status FROM knowledge.document_versions WHERE id=:vid", vid=v1) == "SUPERSEDED"
    assert _scalar("SELECT status FROM knowledge.document_versions WHERE id=:vid", vid=v2) == "READY"
    assert (
        str(_scalar("SELECT current_version_id FROM knowledge.knowledge_sources WHERE id=:sid", sid=source_id))
        == str(v2)
    )
    assert adapter.count_by_generation(gen1) == 0
