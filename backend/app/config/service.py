"""目录/知识库配置与 LLM 配置的服务层。

事务边界约定（DD-17 §6.1）：已纳入审计的可变操作只 flush() 不 commit()，
由 API 层在追加成功审计记录后统一 commit()，保证“业务 + 审计”原子提交。
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import crypto
from ..core.config import get_settings
from ..db.models.catalog import (
    DocumentType,
    Product,
    ProductForm,
    ProductVersion,
    SourcePriority,
)
from ..db.models.config import ConfigRevision, SecretValue

LLM_NAMESPACE = "llm"
LLM_API_KEY_NAME = "api_key"


class ConfigError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


# ---- 目录查询（public，仅启用态） ----

def list_products(db: Session) -> list[Product]:
    return list(db.execute(select(Product).where(Product.status == "ENABLED").order_by(Product.sort_order, Product.name)).scalars())


def list_product_versions(db: Session, product_id) -> list[ProductVersion]:
    return list(db.execute(
        select(ProductVersion).where(
            ProductVersion.product_id == product_id, ProductVersion.status == "ENABLED"
        ).order_by(ProductVersion.sort_order, ProductVersion.version_code)
    ).scalars())


def list_document_types(db: Session) -> list[DocumentType]:
    return list(db.execute(select(DocumentType).where(DocumentType.status == "ENABLED").order_by(DocumentType.sort_order, DocumentType.name)).scalars())


def list_product_forms(db: Session) -> list[ProductForm]:
    return list(db.execute(select(ProductForm).where(ProductForm.status == "ENABLED").order_by(ProductForm.sort_order, ProductForm.name)).scalars())


def list_source_priorities(db: Session) -> list[SourcePriority]:
    return list(db.execute(select(SourcePriority).order_by(SourcePriority.priority)).scalars())


# ---- 管理端列表（含停用态） ----

def admin_list_products(db: Session) -> list[Product]:
    return list(db.execute(select(Product).order_by(Product.sort_order, Product.name)).scalars())


def admin_list_product_versions(db: Session, product_id) -> list[ProductVersion]:
    return list(db.execute(
        select(ProductVersion).where(ProductVersion.product_id == product_id)
        .order_by(ProductVersion.sort_order, ProductVersion.version_code)
    ).scalars())


def admin_list_document_types(db: Session) -> list[DocumentType]:
    return list(db.execute(select(DocumentType).order_by(DocumentType.sort_order, DocumentType.name)).scalars())


def admin_list_product_forms(db: Session) -> list[ProductForm]:
    return list(db.execute(select(ProductForm).order_by(ProductForm.sort_order, ProductForm.name)).scalars())


# ---- 通用 CRUD 辅助 ----

def _unique_error() -> ConfigError:
    return ConfigError("DUPLICATE_CODE", "code 已存在", status=409)


def _update_with_version(db: Session, obj, updates: dict, expected_version: int | None) -> None:
    if expected_version is not None and obj.row_version != expected_version:
        raise ConfigError("VERSION_CONFLICT", "数据已被其他操作修改，请刷新后重试", status=409)
    for key, value in updates.items():
        if value is not None:
            setattr(obj, key, value)
    obj.row_version += 1


# ---- 产品 ----

def create_product(db: Session, data) -> Product:
    product = Product(code=data.code.strip(), name=data.name.strip(), status=data.status, sort_order=data.sort_order)
    db.add(product)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise _unique_error()
    db.refresh(product)
    return product


def update_product(db: Session, product_id, data) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise ConfigError("NOT_FOUND", "产品不存在", status=404)
    _update_with_version(db, product, {"name": data.name, "status": data.status, "sort_order": data.sort_order}, data.row_version)
    db.flush()
    db.refresh(product)
    return product


def set_product_status(db: Session, product_id, status: str) -> Product:
    if status not in ("ENABLED", "DISABLED"):
        raise ConfigError("INVALID_STATUS", "状态不合法", status=400)
    product = db.get(Product, product_id)
    if product is None:
        raise ConfigError("NOT_FOUND", "产品不存在", status=404)
    product.status = status
    db.flush()
    db.refresh(product)
    return product


# ---- 产品版本 ----

def create_product_version(db: Session, product_id, data) -> ProductVersion:
    product = db.get(Product, product_id)
    if product is None:
        raise ConfigError("NOT_FOUND", "产品不存在", status=404)
    if product.status != "ENABLED":
        raise ConfigError("PRODUCT_DISABLED", "产品已停用，不能新增版本", status=409)
    version = ProductVersion(
        product_id=product_id,
        version_code=data.version_code.strip(),
        major_version=data.major_version,
        minor_version=data.minor_version,
        release_date=data.release_date,
        sort_order=data.sort_order,
    )
    db.add(version)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise _unique_error()
    db.refresh(version)
    return version


def update_product_version(db: Session, version_id, data) -> ProductVersion:
    version = db.get(ProductVersion, version_id)
    if version is None:
        raise ConfigError("NOT_FOUND", "版本不存在", status=404)
    _update_with_version(db, version, {
        "version_code": data.version_code,
        "major_version": data.major_version,
        "minor_version": data.minor_version,
        "release_date": data.release_date,
        "status": data.status,
        "sort_order": data.sort_order,
    }, data.row_version)
    db.flush()
    db.refresh(version)
    return version


def set_product_version_status(db: Session, version_id, status: str) -> ProductVersion:
    if status not in ("ENABLED", "DISABLED"):
        raise ConfigError("INVALID_STATUS", "状态不合法", status=400)
    version = db.get(ProductVersion, version_id)
    if version is None:
        raise ConfigError("NOT_FOUND", "版本不存在", status=404)
    version.status = status
    db.flush()
    db.refresh(version)
    return version


# ---- 文档类型 / 产品形态 ----

def create_document_type(db: Session, data) -> DocumentType:
    obj = DocumentType(code=data.code.strip(), name=data.name.strip(), description=data.description, status=data.status, sort_order=data.sort_order)
    db.add(obj)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise _unique_error()
    db.refresh(obj)
    return obj


def update_document_type(db: Session, obj_id, data) -> DocumentType:
    obj = db.get(DocumentType, obj_id)
    if obj is None:
        raise ConfigError("NOT_FOUND", "文档类型不存在", status=404)
    _update_with_version(db, obj, {"name": data.name, "description": data.description, "status": data.status, "sort_order": data.sort_order}, data.row_version)
    db.flush()
    db.refresh(obj)
    return obj


def set_document_type_status(db: Session, obj_id, status: str) -> DocumentType:
    if status not in ("ENABLED", "DISABLED"):
        raise ConfigError("INVALID_STATUS", "状态不合法", status=400)
    obj = db.get(DocumentType, obj_id)
    if obj is None:
        raise ConfigError("NOT_FOUND", "文档类型不存在", status=404)
    obj.status = status
    db.flush()
    db.refresh(obj)
    return obj


def create_product_form(db: Session, data) -> ProductForm:
    obj = ProductForm(code=data.code.strip(), name=data.name.strip(), status=data.status, sort_order=data.sort_order)
    db.add(obj)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise _unique_error()
    db.refresh(obj)
    return obj


def update_product_form(db: Session, obj_id, data) -> ProductForm:
    obj = db.get(ProductForm, obj_id)
    if obj is None:
        raise ConfigError("NOT_FOUND", "产品形态不存在", status=404)
    _update_with_version(db, obj, {"name": data.name, "status": data.status, "sort_order": data.sort_order}, data.row_version)
    db.flush()
    db.refresh(obj)
    return obj


def set_product_form_status(db: Session, obj_id, status: str) -> ProductForm:
    if status not in ("ENABLED", "DISABLED"):
        raise ConfigError("INVALID_STATUS", "状态不合法", status=400)
    obj = db.get(ProductForm, obj_id)
    if obj is None:
        raise ConfigError("NOT_FOUND", "产品形态不存在", status=404)
    obj.status = status
    db.flush()
    db.refresh(obj)
    return obj


# ---- 来源优先级 ----

def update_source_priorities(db: Session, items: list) -> list[SourcePriority]:
    codes = {item.source_code: item.priority for item in items}
    if len(codes) != len(items):
        raise ConfigError("DUPLICATE_SOURCE", "同一来源重复出现", status=400)
    priorities = list(codes.values())
    if len(set(priorities)) != len(priorities):
        raise ConfigError("DUPLICATE_PRIORITY", "优先级不允许重复", status=409)
    for source_code, priority in codes.items():
        row = db.execute(
            select(SourcePriority).where(SourcePriority.source_code == source_code)
        ).scalars().first()
        if row is None:
            raise ConfigError("SOURCE_NOT_FOUND", f"未知来源 {source_code}", status=404)
        row.priority = priority
    db.flush()
    return list_source_priorities(db)


# ---- LLM 配置 ----

def _active_revision(db: Session, namespace: str) -> ConfigRevision | None:
    return db.execute(
        select(ConfigRevision).where(
            ConfigRevision.namespace == namespace, ConfigRevision.status == "ACTIVE"
        )
    ).scalars().first()


def _get_secret(db: Session, namespace: str, key_name: str) -> str | None:
    secret = db.get(SecretValue, (namespace, key_name))
    if secret is None or not secret.ciphertext:
        return None
    return crypto.decrypt(bytes(secret.ciphertext), get_settings().token_enc_key)


def get_llm_config(db: Session) -> dict:
    rev = _active_revision(db, LLM_NAMESPACE)
    content = rev.content if rev else {}
    has_key = _get_secret(db, LLM_NAMESPACE, LLM_API_KEY_NAME) is not None
    return {"config": content, "has_api_key": has_key, "revision": rev.id if rev else None}


def update_llm_config(db: Session, data, user_id) -> dict:
    current = _active_revision(db, LLM_NAMESPACE)
    if current is not None:
        current.status = "RETIRED"
    content = data.model_dump(exclude={"api_key"})
    new_rev = ConfigRevision(
        namespace=LLM_NAMESPACE,
        content=content,
        status="ACTIVE",
        created_by_user_id=user_id,
        activated_at=datetime.now(timezone.utc),
    )
    db.add(new_rev)
    if data.api_key is not None:
        if data.api_key == "":
            secret = db.get(SecretValue, (LLM_NAMESPACE, LLM_API_KEY_NAME))
            if secret is not None:
                db.delete(secret)
        else:
            ciphertext = crypto.encrypt(data.api_key, get_settings().token_enc_key)
            secret = db.get(SecretValue, (LLM_NAMESPACE, LLM_API_KEY_NAME))
            if secret is None:
                secret = SecretValue(
                    namespace=LLM_NAMESPACE, key_name=LLM_API_KEY_NAME,
                    ciphertext=ciphertext, key_version="1",
                )
                db.add(secret)
            else:
                secret.ciphertext = ciphertext
    db.flush()
    return get_llm_config(db)


def test_llm_config(db: Session, data) -> dict:
    if not data.enabled or not data.base_url or not data.model:
        return {"ok": False, "message": "需先启用并填写 base_url 与 model"}
    api_key = data.api_key if data.api_key not in (None, "") else _get_secret(db, LLM_NAMESPACE, LLM_API_KEY_NAME)
    if not api_key:
        return {"ok": False, "message": "未配置 API Key"}
    url = f"{data.base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": data.model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}
    try:
        resp = httpx.post(url, headers=headers, json=payload, timeout=data.timeout_seconds)
        if 200 <= resp.status_code < 300:
            return {"ok": True, "message": f"连接成功（HTTP {resp.status_code}）"}
        return {"ok": False, "message": f"服务返回 HTTP {resp.status_code}: {resp.text[:120]}"}
    except httpx.TimeoutException:
        return {"ok": False, "message": "连接超时"}
    except httpx.HTTPError as exc:
        return {"ok": False, "message": f"连接失败: {exc}"}
