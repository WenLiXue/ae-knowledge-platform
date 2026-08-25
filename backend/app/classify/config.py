"""分类配置（DD-05 §4、DD-19 §15）。

- 阈值 / Prompt revision / 输入预算 / 相关性定义来自
  `platform.config_revisions(namespace='classification')` 的 ACTIVE 版本；
  未配置时使用代码默认值，`config_revision=0`。
- taxonomy 不落配置：实时从知识库目录表（ENABLED）构建，保证前后端与数据库
  只有一套稳定 code（AC-CLS-001）。任务只使用启动时绑定的快照。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models.catalog import DocumentType, Product, ProductForm, ProductVersion
from ..db.models.config import ConfigRevision

CLASSIFICATION_NAMESPACE = "classification"
CLASSIFICATION_SCHEMA_VERSION = "1"
PROMPT_REVISION = "1"
INPUT_BUILDER_REVISION = "1"

DEFAULT_THRESHOLDS = {"relevant": 0.80, "irrelevant": 0.90}
DEFAULT_BUDGET = {
    "max_blocks": 80,
    "max_chars_per_block": 600,
    "total_chars": 20_000,
    "max_table_rows": 4,
}
DEFAULT_RELEVANCE_POLICY = {
    "definition": (
        "与目标产品的规格、功能、版本、部署、测试、开发设计、技术支持或问题案件直接相关"
    ),
    "positive_examples": [],
    "negative_examples": [],
}


@dataclass(frozen=True)
class ClassificationConfig:
    """一次分类任务绑定的配置快照。"""

    config_revision: int = 0
    schema_version: str = CLASSIFICATION_SCHEMA_VERSION
    prompt_revision: str = PROMPT_REVISION
    input_builder_revision: str = INPUT_BUILDER_REVISION
    thresholds: dict = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))
    budget: dict = field(default_factory=lambda: dict(DEFAULT_BUDGET))
    relevance_policy: dict = field(default_factory=lambda: dict(DEFAULT_RELEVANCE_POLICY))
    taxonomy: dict = field(default_factory=dict)


def _active_config_revision(db: Session) -> ConfigRevision | None:
    return db.execute(
        select(ConfigRevision).where(
            ConfigRevision.namespace == CLASSIFICATION_NAMESPACE,
            ConfigRevision.status == "ACTIVE",
        )
    ).scalars().first()


def build_taxonomy(db: Session) -> dict:
    """当前启用目录快照（产品/版本/文档类型/产品形态），含 id 便于 code→id 解析。"""
    products = {
        p.id: {"id": str(p.id), "code": p.code, "name": p.name}
        for p in db.execute(
            select(Product).where(Product.status == "ENABLED").order_by(Product.sort_order, Product.name)
        ).scalars()
    }
    versions = [
        {
            "id": str(v.id),
            "product_id": str(v.product_id),
            "product_code": products[v.product_id]["code"] if v.product_id in products else None,
            "code": v.version_code,
        }
        for v in db.execute(
            select(ProductVersion)
            .where(ProductVersion.status == "ENABLED")
            .order_by(ProductVersion.sort_order, ProductVersion.version_code)
        ).scalars()
    ]
    document_types = [
        {"id": str(t.id), "code": t.code, "name": t.name}
        for t in db.execute(
            select(DocumentType)
            .where(DocumentType.status == "ENABLED")
            .order_by(DocumentType.sort_order, DocumentType.name)
        ).scalars()
    ]
    product_forms = [
        {"id": str(f.id), "code": f.code, "name": f.name}
        for f in db.execute(
            select(ProductForm)
            .where(ProductForm.status == "ENABLED")
            .order_by(ProductForm.sort_order, ProductForm.name)
        ).scalars()
    ]
    return {
        "products": list(products.values()),
        "product_versions": versions,
        "document_types": document_types,
        "product_forms": product_forms,
    }


def load_classification_config(db: Session) -> ClassificationConfig:
    """读取当前 ACTIVE classification 配置并合并目录快照。

    未配置时返回代码默认值（config_revision=0）；已配置时缺失字段回退默认值，
    保证向前兼容。只读，不触发写入。
    """
    rev = _active_config_revision(db)
    taxonomy = build_taxonomy(db)
    if rev is None:
        return ClassificationConfig(taxonomy=taxonomy)

    content = rev.content or {}
    thresholds = dict(DEFAULT_THRESHOLDS)
    budget = dict(DEFAULT_BUDGET)
    relevance_policy = dict(DEFAULT_RELEVANCE_POLICY)
    content_thresholds = content.get("thresholds") or {}
    content_budget = content.get("budget") or {}
    content_policy = content.get("relevance_policy") or {}
    for key, default in DEFAULT_THRESHOLDS.items():
        if isinstance(content_thresholds.get(key), (int, float)):
            thresholds[key] = float(content_thresholds[key])
    for key, default in DEFAULT_BUDGET.items():
        if isinstance(content_budget.get(key), (int, float)):
            budget[key] = int(content_budget[key])
    if isinstance(content_policy.get("definition"), str) and content_policy["definition"]:
        relevance_policy = {
            "definition": content_policy["definition"],
            "positive_examples": list(content_policy.get("positive_examples") or []),
            "negative_examples": list(content_policy.get("negative_examples") or []),
        }

    return ClassificationConfig(
        config_revision=rev.id,
        schema_version=str(content.get("schema_version") or CLASSIFICATION_SCHEMA_VERSION),
        prompt_revision=str(content.get("prompt_revision") or PROMPT_REVISION),
        input_builder_revision=str(content.get("input_builder_revision") or INPUT_BUILDER_REVISION),
        thresholds=thresholds,
        budget=budget,
        relevance_policy=relevance_policy,
        taxonomy=taxonomy,
    )
