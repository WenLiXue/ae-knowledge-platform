"""LLM 模型管理与服务配置的服务层（DD-20 §8、§9、§11）。

事务边界约定（DD-17 §6.1）：已纳入审计的可变操作只 flush() 不 commit()，
由 API 层在追加成功审计记录后统一 commit()，保证“业务 + 审计”原子提交。

数据存储（§8）：
- platform.config_revisions（namespace="llm"）：模型列表 + 服务绑定的版本快照，
  单个 ACTIVE revision 的 content 结构为 schema_version=2；
- platform.secret_values（namespace="llm_model"，key_name=模型配置 ID）：
  每个模型配置的 API Key 密文。revision 只根据是否存在 SecretValue 计算 has_api_key，
  绝不保存密钥明文、密文或摘要。
"""

from __future__ import annotations

import ipaddress
import json
import logging
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import crypto
from ..core.config import get_settings
from ..db.models.config import ConfigRevision, SecretValue

logger = logging.getLogger("app.llm")

LLM_NAMESPACE = "llm"
LLM_SCHEMA_VERSION = 2
MODEL_SECRET_NAMESPACE = "llm_model"
# V1 模型类型与服务类型的受控枚举（DD-20 §4.3）
MODEL_TYPES = ("CHAT", "EMBEDDING", "RERANK")
# 服务商为受控标签（DD-20 §6.2 至少支持 openai-compatible）：V1 协议行为统一走
# openai-compatible 适配器，服务商名称仅作识别用途；适配器映射由 DD-19 后续接入。
ALL_SERVICE_TYPES = ("QA", "DOCUMENT_CLASSIFICATION", "DOCUMENT_EMBEDDING", "RETRIEVAL_RERANK")
# 连接测试统一超时（系统维护，不向管理员暴露）
LLM_TEST_TIMEOUT_SECONDS = 60


class LLMConfigError(Exception):
    """LLM 配置领域错误。code 对齐 DD-20 §10 稳定错误码。"""

    def __init__(self, code: str, message: str, *, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class ServiceDef:
    service_type: str
    display_name: str
    description: str
    required: bool
    model_types: tuple[str, ...]


# 服务类型为稳定业务枚举（DD-20 §4.3）。"是否必配"表示业务投入使用前必须配置，
# 不表示保存时强制非空。
SERVICE_DEFS: dict[str, ServiceDef] = {
    "QA": ServiceDef("QA", "智能问答", "用于知识查询的答案生成。", True, ("CHAT",)),
    "DOCUMENT_CLASSIFICATION": ServiceDef("DOCUMENT_CLASSIFICATION", "文档自动分类", "用于判断文档相关性并生成分类建议。", True, ("CHAT",)),
    "DOCUMENT_EMBEDDING": ServiceDef("DOCUMENT_EMBEDDING", "文档向量化", "用于生成知识库向量索引。", True, ("EMBEDDING",)),
    "RETRIEVAL_RERANK": ServiceDef("RETRIEVAL_RERANK", "检索重排", "可选；未配置时使用融合检索顺序。", False, ("RERANK",)),
}


# ---- revision 与 state 读取 ----

def _active_revision(db: Session) -> ConfigRevision | None:
    return db.execute(
        select(ConfigRevision).where(
            ConfigRevision.namespace == LLM_NAMESPACE, ConfigRevision.status == "ACTIVE"
        )
    ).scalars().first()


def _empty_state() -> dict:
    return {
        "schema_version": LLM_SCHEMA_VERSION,
        "models": {},
        "bindings": {st: None for st in ALL_SERVICE_TYPES},
    }


def _load_state(db: Session) -> tuple[ConfigRevision | None, dict]:
    """读取当前 ACTIVE revision 并解析为内部 state。

    只读，不触发迁移写入。ACTIVE 缺失或尚为旧版 schema 时按空 v2 状态处理，
    保证只读接口在迁移前也不抛错（正式迁移由启动钩子与首个写操作完成）。
    """
    rev = _active_revision(db)
    if rev is None:
        return None, _empty_state()
    content = rev.content or {}
    if content.get("schema_version") != LLM_SCHEMA_VERSION:
        logger.warning("llm_config_non_v2_revision id=%s schema_version=%s", rev.id, content.get("schema_version"))
        return rev, _empty_state()
    models: dict[str, dict] = {}
    for item in content.get("models") or []:
        if isinstance(item, dict) and item.get("id"):
            models[item["id"]] = item
    raw_bindings = content.get("service_bindings") or {}
    bindings = {st: raw_bindings.get(st) for st in ALL_SERVICE_TYPES}
    return rev, {"schema_version": LLM_SCHEMA_VERSION, "models": models, "bindings": bindings}


def _build_content(state: dict) -> dict:
    return {
        "schema_version": LLM_SCHEMA_VERSION,
        "models": list(state["models"].values()),
        "service_bindings": {st: state["bindings"][st] for st in ALL_SERVICE_TYPES},
    }


def _write_revision(
    db: Session,
    state: dict,
    *,
    user_id,
    expected_revision: int | None,
) -> ConfigRevision:
    """原子替换当前 revision：校验版本、退休旧版、写入新 ACTIVE（DD-20 §8.3）。

    并发更新依靠“同一 namespace 只有一个 ACTIVE revision”的唯一约束兜底。
    """
    current = _active_revision(db)
    if expected_revision is not None:
        if current is None or current.id != expected_revision:
            raise LLMConfigError(
                "CONFIG_VERSION_CONFLICT",
                "配置已被其他管理员修改，请刷新后重试",
                status=409,
            )
    if current is not None:
        current.status = "RETIRED"
    new_rev = ConfigRevision(
        namespace=LLM_NAMESPACE,
        content=_build_content(state),
        status="ACTIVE",
        created_by_user_id=user_id,
        activated_at=datetime.now(timezone.utc),
    )
    db.add(new_rev)
    db.flush()
    return new_rev


# ---- 密钥读写 ----

def _get_secret(db: Session, key_name: str, *, namespace: str = MODEL_SECRET_NAMESPACE) -> str | None:
    secret = db.get(SecretValue, (namespace, key_name))
    if secret is None or not secret.ciphertext:
        return None
    return crypto.decrypt(bytes(secret.ciphertext), get_settings().token_enc_key)


def _set_secret(db: Session, key_name: str, plaintext: str, *, namespace: str = MODEL_SECRET_NAMESPACE) -> None:
    ciphertext = crypto.encrypt(plaintext, get_settings().token_enc_key)
    secret = db.get(SecretValue, (namespace, key_name))
    if secret is None:
        db.add(
            SecretValue(
                namespace=namespace,
                key_name=key_name,
                ciphertext=ciphertext,
                key_version="1",
            )
        )
    else:
        secret.ciphertext = ciphertext


def _delete_secret(db: Session, key_name: str, *, namespace: str = MODEL_SECRET_NAMESPACE) -> None:
    secret = db.get(SecretValue, (namespace, key_name))
    if secret is not None:
        db.delete(secret)


# ---- 校验辅助 ----

def _normalize_base_url(url: str) -> str:
    """移除末尾 / 并校验协议（DD-20 §6.2）。"""
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise LLMConfigError("INVALID_MODEL_ENDPOINT", "Base URL 必须以 http:// 或 https:// 开头", status=422)
    return url


def _validate_endpoint(url: str) -> None:
    """SSRF 防护（DD-12）：生产环境禁止环回、链路本地、组播与云元数据地址。

    开发/测试环境允许 localhost，便于本地联调与自动化测试。生产启用真实能力前
    应结合已登记 Endpoint 白名单使用。
    """
    if get_settings().environment != "production":
        return
    host = urlsplit(url).hostname or ""
    if not host:
        raise LLMConfigError("INVALID_MODEL_ENDPOINT", "Base URL 缺少主机名", status=422)
    try:
        addrs = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise LLMConfigError("INVALID_MODEL_ENDPOINT", "无法解析服务地址", status=422) from exc
    for _, _, _, _, sockaddr in addrs:
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            raise LLMConfigError("INVALID_MODEL_ENDPOINT", "服务地址不允许指向环回/链路本地/元数据地址", status=422)


def _check_model_type(model_type: str) -> None:
    if model_type not in MODEL_TYPES:
        raise LLMConfigError("INVALID_MODEL_TYPE", "模型类型不合法", status=422)


def _check_provider(provider: str) -> None:
    if not provider or not provider.strip():
        raise LLMConfigError("INVALID_PROVIDER", "服务商不能为空", status=422)


def _check_name_unique(state: dict, exclude_id: str | None, name: str) -> None:
    for mid, model in state["models"].items():
        if mid == exclude_id:
            continue
        if model["name"] == name:
            raise LLMConfigError("MODEL_CONFIG_NAME_DUPLICATE", "配置名称重复，请更换名称", status=409)


def _find_model(state: dict, model_id: str) -> dict:
    model = state["models"].get(model_id)
    if model is None:
        raise LLMConfigError("MODEL_CONFIG_NOT_FOUND", "模型配置不存在", status=404)
    return model


def _used_by(state: dict, model_id: str) -> list[str]:
    return [st for st, mid in state["bindings"].items() if mid == model_id]


def _in_use_message(services: list[str]) -> str:
    names = "、".join(SERVICE_DEFS[st].display_name for st in services if st in SERVICE_DEFS)
    return f"该模型正在被服务使用（{names}）。请先在“服务配置”中解除或更换绑定。"


def _model_out(db: Session, state: dict, model: dict) -> dict:
    return {
        "id": model["id"],
        "name": model["name"],
        "model_type": model["model_type"],
        "provider": model["provider"],
        "base_url": model["base_url"],
        "model_name": model["model_name"],
        "enabled": model["enabled"],
        "has_api_key": _get_secret(db, model["id"]) is not None,
        "used_by": _used_by(state, model["id"]),
    }


# ---- 模型管理 ----

def list_models(db: Session) -> dict:
    rev, state = _load_state(db)
    return {
        "revision": rev.id if rev is not None else None,
        "items": [_model_out(db, state, m) for m in state["models"].values()],
    }


def create_model(db: Session, data, user_id) -> dict:
    from .migration import ensure_llm_schema_v2

    ensure_llm_schema_v2(db, user_id=user_id)
    rev, state = _load_state(db)
    name = data.name.strip()
    model_name = data.model_name.strip()
    base_url = _normalize_base_url(data.base_url)
    _validate_endpoint(base_url)
    _check_provider(data.provider)
    _check_name_unique(state, None, name)

    model_id = str(uuid.uuid4())
    model = {
        "id": model_id,
        "name": name,
        "model_type": data.model_type,
        "provider": data.provider,
        "base_url": base_url,
        "model_name": model_name,
        "enabled": data.enabled,
    }
    state["models"][model_id] = model
    if data.api_key is not None and data.api_key != "":
        _set_secret(db, model_id, data.api_key)
    _write_revision(db, state, user_id=user_id, expected_revision=data.expected_revision)
    return _model_out(db, state, model)


def update_model(db: Session, model_id: str, data, user_id) -> dict:
    from .migration import ensure_llm_schema_v2

    ensure_llm_schema_v2(db, user_id=user_id)
    rev, state = _load_state(db)
    model = _find_model(state, model_id)
    used_by = _used_by(state, model_id)

    # 已被服务引用时禁止修改模型类型（DD-20 §6.3）
    if data.model_type is not None and data.model_type != model["model_type"] and used_by:
        raise LLMConfigError("MODEL_CONFIG_IN_USE", _in_use_message(used_by), status=409)

    if data.name is not None:
        name = data.name.strip()
        _check_name_unique(state, model_id, name)
        model["name"] = name
    if data.model_type is not None:
        _check_model_type(data.model_type)
        model["model_type"] = data.model_type
    if data.provider is not None:
        _check_provider(data.provider)
        model["provider"] = data.provider
    if data.base_url is not None:
        base_url = _normalize_base_url(data.base_url)
        _validate_endpoint(base_url)
        model["base_url"] = base_url
    if data.model_name is not None:
        model["model_name"] = data.model_name.strip()
    if data.enabled is not None:
        if not data.enabled and model["enabled"] and used_by:
            raise LLMConfigError("MODEL_CONFIG_IN_USE", _in_use_message(used_by), status=409)
        model["enabled"] = data.enabled
    if data.api_key not in (None, ""):
        _set_secret(db, model_id, data.api_key)

    _write_revision(db, state, user_id=user_id, expected_revision=data.expected_revision)
    return _model_out(db, state, model)


def set_model_enabled(db: Session, model_id: str, enabled: bool, user_id) -> dict:
    from .migration import ensure_llm_schema_v2

    ensure_llm_schema_v2(db, user_id=user_id)
    rev, state = _load_state(db)
    model = _find_model(state, model_id)
    used_by = _used_by(state, model_id)
    if not enabled and used_by:
        raise LLMConfigError("MODEL_CONFIG_IN_USE", _in_use_message(used_by), status=409)
    model["enabled"] = enabled
    _write_revision(db, state, user_id=user_id, expected_revision=None)
    return _model_out(db, state, model)


# ---- 连接测试 ----

def _classify_test_failure(status_code: int) -> tuple[str, str]:
    if status_code in (401, 403):
        return "MODEL_TEST_AUTH_FAILED", "鉴权失败：请检查 API Key 是否正确"
    if status_code == 404:
        return "MODEL_TEST_NOT_FOUND", "接口不存在：请检查 Base URL 是否以 /v1 结尾"
    return "MODEL_TEST_PROTOCOL_ERROR", f"服务返回 HTTP {status_code}"


def _auth_headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _default_client(timeout: float) -> httpx.Client:
    """连接测试的默认 HTTP 客户端；测试可替换为注入 MockTransport 的工厂。"""
    return httpx.Client(timeout=timeout)


def _test_chat(client: httpx.Client, url: str, model_name: str, api_key: str) -> tuple[bool, str, int | None]:
    payload = {"model": model_name, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}
    resp = client.post(url, headers=_auth_headers(api_key), json=payload)
    if not 200 <= resp.status_code < 300:
        code, message = _classify_test_failure(resp.status_code)
        return False, f"{message}（{code}）", None
    try:
        resp.json()
    except (json.JSONDecodeError, ValueError):
        return False, "响应不是合法 JSON（MODEL_TEST_PROTOCOL_ERROR）", None
    return True, "连接成功", None


def _test_embedding(client: httpx.Client, url: str, model_name: str, api_key: str) -> tuple[bool, str, int | None]:
    payload = {"model": model_name, "input": "ping"}
    resp = client.post(url, headers=_auth_headers(api_key), json=payload)
    if not 200 <= resp.status_code < 300:
        code, message = _classify_test_failure(resp.status_code)
        return False, f"{message}（{code}）", None
    try:
        body = resp.json()
    except (json.JSONDecodeError, ValueError):
        return False, "响应不是合法 JSON（MODEL_TEST_PROTOCOL_ERROR）", None
    try:
        embedding = body["data"][0]["embedding"]
        if not isinstance(embedding, list) or not embedding or not all(isinstance(x, (int, float)) for x in embedding):
            raise KeyError
        return True, f"连接成功，向量维度 {len(embedding)}", len(embedding)
    except (KeyError, IndexError, TypeError):
        return False, "响应缺少非空数值向量（MODEL_TEST_PROTOCOL_ERROR）", None


def _test_rerank(client: httpx.Client, url: str, model_name: str, api_key: str) -> tuple[bool, str, int | None]:
    payload = {"model": model_name, "query": "ping", "documents": ["测试候选 A", "测试候选 B"]}
    resp = client.post(url, headers=_auth_headers(api_key), json=payload)
    if not 200 <= resp.status_code < 300:
        code, message = _classify_test_failure(resp.status_code)
        return False, f"{message}（{code}）", None
    try:
        resp.json()
    except (json.JSONDecodeError, ValueError):
        return False, "响应不是合法 JSON（MODEL_TEST_PROTOCOL_ERROR）", None
    return True, "连接成功", None


def test_model(db: Session, data, *, user_id=None, client: httpx.Client | None = None) -> dict:
    """连接测试（DD-20 §6.5、§9.3）。

    只返回成功/失败、耗时、必要的错误分类；绝不把上游原始响应、完整正文或密钥
    返回浏览器或写入日志。测试不改变配置状态，也不自动保存或绑定服务。
    """
    api_key = data.api_key if data.api_key not in (None, "") else None
    effective_type = data.model_type
    resolved_name = data.model_name
    base_url = _normalize_base_url(data.base_url)
    _validate_endpoint(base_url)
    _check_model_type(effective_type)

    # 提供 model_id 时使用已保存密钥与已保存的连接信息（DD-20 §9.3）
    if api_key is None and data.model_id:
        _, state = _load_state(db)
        model = _find_model(state, data.model_id)
        api_key = _get_secret(db, model["id"])
        if api_key is None:
            return {"ok": False, "message": "该模型未配置 API Key", "duration_ms": 0.0, "dimension": None}
        base_url = _normalize_base_url(model["base_url"])
        resolved_name = model["model_name"]
        effective_type = model["model_type"]
        _check_model_type(effective_type)

    if api_key is None:
        return {"ok": False, "message": "未配置 API Key，无法测试", "duration_ms": 0.0, "dimension": None}

    path = {
        "CHAT": "chat/completions",
        "EMBEDDING": "embeddings",
        "RERANK": "rerank",
    }.get(effective_type)
    url = f"{base_url}/{path}"

    started = datetime.now(timezone.utc)
    test_client = client if client is not None else _default_client(LLM_TEST_TIMEOUT_SECONDS)
    try:
        if effective_type == "CHAT":
            ok, message, dimension = _test_chat(test_client, url, resolved_name, api_key)
        elif effective_type == "EMBEDDING":
            ok, message, dimension = _test_embedding(test_client, url, resolved_name, api_key)
        else:
            ok, message, dimension = _test_rerank(test_client, url, resolved_name, api_key)
    except httpx.TimeoutException:
        ok, message, dimension = False, "连接超时（MODEL_TEST_TIMEOUT）", None
    except httpx.HTTPError as exc:
        ok, message, dimension = False, f"网络连接失败: {exc}（MODEL_TEST_NETWORK_ERROR）", None
    finally:
        if client is None:
            test_client.close()
    duration_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000

    logger.log(
        logging.INFO if ok else logging.WARNING,
        "llm_connection_test user_id=%s model_type=%s model=%s result=%s duration_ms=%.0f",
        user_id, effective_type, resolved_name, "ok" if ok else "failed", duration_ms,
        extra={
            "user_id": str(user_id) if user_id is not None else None,
            "result": "ok" if ok else "failed",
            "duration_ms": round(duration_ms, 3),
        },
    )
    return {"ok": ok, "message": message, "duration_ms": duration_ms, "dimension": dimension}


# ---- 服务配置 ----

def get_service_bindings(db: Session) -> dict:
    rev, state = _load_state(db)
    services = []
    for st in ALL_SERVICE_TYPES:
        definition = SERVICE_DEFS[st]
        model_id = state["bindings"].get(st)
        model = state["models"].get(model_id) if model_id else None
        services.append(
            {
                "service_type": st,
                "display_name": definition.display_name,
                "description": definition.description,
                "required": definition.required,
                "model": {"id": model["id"], "name": model["name"], "model_name": model["model_name"]} if model else None,
            }
        )
    return {
        "revision": rev.id if rev is not None else None,
        "services": services,
        "models": [_model_out(db, state, m) for m in state["models"].values()],
    }


def update_service_bindings(db: Session, data, user_id) -> dict:
    from .migration import ensure_llm_schema_v2

    ensure_llm_schema_v2(db, user_id=user_id)
    rev, state = _load_state(db)
    unknown = set(data.bindings) - set(ALL_SERVICE_TYPES)
    if unknown:
        raise LLMConfigError("INVALID_SERVICE_TYPE", f"未知服务类型: {', '.join(sorted(unknown))}", status=422)

    # 原子校验全部绑定；任一绑定不合法时不保存任何一项（DD-20 §9.2）
    for service_type, model_id in data.bindings.items():
        if model_id is None:
            continue
        model = _find_model(state, model_id)
        if not model["enabled"]:
            raise LLMConfigError("MODEL_CONFIG_DISABLED", f"{SERVICE_DEFS[service_type].display_name} 选择的模型已停用", status=409)
        if model["model_type"] not in SERVICE_DEFS[service_type].model_types:
            raise LLMConfigError(
                "MODEL_TYPE_MISMATCH",
                f"{SERVICE_DEFS[service_type].display_name} 需要 {SERVICE_DEFS[service_type].model_types[0]} 类型的模型，当前为 {model['model_type']}",
                status=409,
            )

    for service_type, model_id in data.bindings.items():
        state["bindings"][service_type] = model_id
    _write_revision(db, state, user_id=user_id, expected_revision=data.expected_revision)
    return get_service_bindings(db)
