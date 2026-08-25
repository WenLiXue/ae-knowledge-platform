"""旧版 LLM 配置迁移到 schema_version=2（DD-20 §12）。

- 旧版 `llm` revision 为单条结构（model/classification_model/embedding_model + 全局连接信息）；
- 迁移到 v2 时生成模型列表与服务绑定，并把旧全局 API Key 密文复制到各模型 SecretValue；
- 幂等：检测到 schema_version >= 2 时不重复生成模型；旧 revision 保留为 RETIRED 供审计回溯。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..db.models.config import ConfigRevision
from .service import (
    ALL_SERVICE_TYPES,
    LLM_NAMESPACE,
    LLM_SCHEMA_VERSION,
    _active_revision,
    _build_content,
    _delete_secret,
    _empty_state,
    _get_secret,
    _set_secret,
)


def ensure_llm_schema_v2(db: Session, *, user_id=None) -> bool:
    """确保当前 llm 配置为 schema_version=2。

    无 ACTIVE revision 时创建空 v2（空模型列表 + 空绑定，不生成占位模型）；
    已是 v2 时 no-op。返回是否发生了写入。必须在调用方事务内使用并提交。
    """
    current = _active_revision(db)
    if current is None:
        db.add(
            ConfigRevision(
                namespace=LLM_NAMESPACE,
                content=_build_content(_empty_state()),
                status="ACTIVE",
                created_by_user_id=user_id,
                activated_at=datetime.now(timezone.utc),
            )
        )
        db.flush()
        return True
    content = current.content or {}
    if content.get("schema_version") == LLM_SCHEMA_VERSION:
        return False
    _migrate_legacy(db, current, user_id)
    return True


def _migrate_legacy(db: Session, old_rev: ConfigRevision, user_id=None) -> None:
    content = old_rev.content or {}
    base_url = str(content.get("base_url") or "").rstrip("/")
    provider = str(content.get("provider") or "openai-compatible")
    enabled = bool(content.get("enabled", False))
    old_key = _get_secret(db, "api_key", namespace=LLM_NAMESPACE)

    models: dict[str, dict] = {}
    bindings = {st: None for st in ALL_SERVICE_TYPES}

    def add_model(name: str, model_type: str, model_name: str) -> str:
        model_id = str(uuid.uuid4())
        models[model_id] = {
            "id": model_id,
            "name": name,
            "model_type": model_type,
            "provider": provider,
            "base_url": base_url,
            "model_name": model_name,
            "enabled": enabled,
        }
        if old_key is not None:
            _set_secret(db, model_id, old_key)
        return model_id

    # 1. model → CHAT 模型并绑定 QA（DD-20 §12.1）
    chat = str(content.get("model") or "").strip()
    if chat:
        bindings["QA"] = add_model("对话模型", "CHAT", chat)

    # 2. classification_model → 复用同名同 Endpoint 的 CHAT 或新建，绑定 DOCUMENT_CLASSIFICATION
    class_model = str(content.get("classification_model") or "").strip()
    if class_model:
        reuse = next(
            (
                mid for mid, m in models.items()
                if m["model_type"] == "CHAT" and m["model_name"] == class_model and m["base_url"] == base_url
            ),
            None,
        )
        bindings["DOCUMENT_CLASSIFICATION"] = reuse or add_model("分类模型", "CHAT", class_model)

    # 3. embedding_model → EMBEDDING 模型并绑定 DOCUMENT_EMBEDDING
    embed = str(content.get("embedding_model") or "").strip()
    if embed:
        bindings["DOCUMENT_EMBEDDING"] = add_model("向量模型", "EMBEDDING", embed)

    # 4. 旧版没有 Rerank 字段，RETRIEVAL_RERANK 保持 null（DD-20 §12.4）

    old_rev.status = "RETIRED"
    db.add(
        ConfigRevision(
            namespace=LLM_NAMESPACE,
            content=_build_content(
                {"schema_version": LLM_SCHEMA_VERSION, "models": models, "bindings": bindings}
            ),
            status="ACTIVE",
            created_by_user_id=user_id,
            activated_at=datetime.now(timezone.utc),
        )
    )

    # 6. 确认新密钥可读取后删除旧 llm/api_key（DD-20 §12.6）。
    # 先 flush 使新模型 SecretValue 可被同一事务读取，再比较明文后删除旧密钥。
    db.flush()
    if old_key is not None and models:
        sample_id = next(iter(models))
        if _get_secret(db, sample_id) == old_key:
            _delete_secret(db, "api_key", namespace=LLM_NAMESPACE)
    db.flush()
