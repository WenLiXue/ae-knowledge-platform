"""LLM 配置的运行时解析器（DD-20 §11）。

分类器、问答、Embedding 和 Rerank 业务不得自行读取页面字段或拼装模型名称，
统一按 service_type 解析当前 ACTIVE llm revision 中的绑定与模型连接信息。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from .service import (
    ALL_SERVICE_TYPES,
    SERVICE_DEFS,
    LLMConfigError,
    _get_secret,
    _load_state,
)


@dataclass(frozen=True)
class ResolvedModel:
    """一次业务调用开始时解析并固定的模型连接（DD-20 §11）。

    调用过程中即使管理员发布新配置，也不改变本次调用的解析结果。
    """

    service_type: str
    config_revision: int | None
    model_config_id: str
    provider: str
    base_url: str
    model_name: str
    api_key: str | None


def resolve_service_model(db: Session, service_type: str) -> ResolvedModel | None:
    """解析指定业务服务使用的模型连接。

    返回 None 表示该服务未配置（仅对可选服务，如 RETRIEVAL_RERANK，调用方应降级）；
    必配服务未配置、模型被删除/停用或缺少密钥时抛出 LLMConfigError。
    """
    if service_type not in ALL_SERVICE_TYPES:
        raise LLMConfigError("INVALID_SERVICE_TYPE", f"未知服务类型: {service_type}", status=422)

    rev, state = _load_state(db)
    model_id = state["bindings"].get(service_type)
    if not model_id:
        if SERVICE_DEFS[service_type].required:
            raise LLMConfigError(
                "REQUIRED_SERVICE_MODEL_MISSING",
                f"{SERVICE_DEFS[service_type].display_name} 未配置模型，请先在“服务配置”中完成配置",
                status=409,
            )
        return None

    model = state["models"].get(model_id)
    if model is None:
        raise LLMConfigError("MODEL_CONFIG_NOT_FOUND", "服务绑定的模型配置不存在", status=404)
    if not model["enabled"]:
        raise LLMConfigError("MODEL_CONFIG_DISABLED", f"{SERVICE_DEFS[service_type].display_name} 使用的模型已停用", status=409)

    api_key = _get_secret(db, model_id)
    if api_key is None:
        raise LLMConfigError(
            "MODEL_CONFIG_MISSING_KEY",
            f"{SERVICE_DEFS[service_type].display_name} 使用的模型未配置 API Key",
            status=409,
        )

    return ResolvedModel(
        service_type=service_type,
        config_revision=rev.id if rev is not None else None,
        model_config_id=model["id"],
        provider=model["provider"],
        base_url=model["base_url"],
        model_name=model["model_name"],
        api_key=api_key,
    )
