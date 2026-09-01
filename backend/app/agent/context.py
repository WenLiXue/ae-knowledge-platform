"""Agent 运行上下文（DD-21 §5.3）：运行依赖，不进入 checkpoint。

通过 LangGraph context_schema 注入；每个数据库节点自行创建短生命周期 Session，
任何远程调用前必须结束数据库事务和锁。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterator

from sqlalchemy.orm import Session

from ..chunking.tokens import estimate_tokens
from ..core.config import Settings, get_settings
from ..llm.runtime import resolve_service_model
from ..model_gateway import create_gateway
from ..model_gateway.base import ChatResponse, GatewayTool, ModelGateway
from ..qa.llm import chat_with_retry
from ..retrieval.service import RetrievalService, build_retrieval_service
from .tools import ToolExecutor, ToolRegistry, build_default_tool_registry
from .tools.policy import ToolPolicy


@dataclass(frozen=True)
class PrincipalContext:
    """Authenticated principal resolved outside the tool planner."""

    user_id: str
    username: str | None
    display_name: str
    is_admin: bool
    status: str


class TokenEstimator:
    """确定性 token 近似估算（复用 chunking/tokens.estimate_tokens，无外部 tokenizer）。"""

    def estimate(self, text: str) -> int:
        return estimate_tokens(text or "")

    def estimate_list(self, texts: list[str]) -> int:
        return sum(self.estimate(t) for t in texts)


class AgentModels:
    """模型访问的唯一出口（DD-21 §19 B 阶段：只适配 model_gateway）。

    - 测试注入 ``chat_fn`` 时直接调用（不解析模型、不调用网关）；
    - 生产按 ``QA`` 服务类型解析模型并调用网关（传输重试沿用 chat_with_retry，最多 3 次）。
    解析发生在短事务内并先提交释放读事务，再执行外部 HTTP。
    """

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] | None = None,
        resolve_model: Callable[[Session, str], object] | None = None,
        gateway_factory: Callable[[object], ModelGateway] | None = None,
        chat_fn: Callable[[list[dict]], str] | None = None,
    ):
        self._session_factory = session_factory
        self._resolve_model = resolve_model or resolve_service_model
        self._gateway_factory = gateway_factory or create_gateway
        self._chat_fn = chat_fn
        self._last_model_key: str | None = None

    @property
    def injected(self) -> bool:
        return self._chat_fn is not None

    @property
    def last_model_key(self) -> str | None:
        return self._last_model_key

    def chat(
        self,
        messages: list[dict],
        *,
        max_tokens: int = 4096,
        timeout_seconds: float | None = None,
        response_format: dict | None = None,
    ) -> str:
        """调用 QA 模型。messages 为 [{role, content}, ...]；返回文本。"""
        if self._chat_fn is not None:
            return self._chat_fn(messages)
        if self._session_factory is None:
            raise ValueError("AgentModels 未配置 session_factory，无法解析 QA 模型")
        with self._session_factory() as db:
            resolved = self._resolve_model(db, "QA")
            self._last_model_key = resolved.model_config_id
            try:
                gateway = self._gateway_factory(
                    resolved,
                    **({"total_timeout": timeout_seconds, "retries": 0} if timeout_seconds else {}),
                )
            except TypeError:
                gateway = self._gateway_factory(resolved)
            model_name = resolved.model_name
            # 读配置的短事务在此结束，外部 HTTP 不持有 DB 事务/行锁
            db.commit()
        return chat_with_retry(
            gateway,
            model_name,
            messages,
            max_tokens=max_tokens,
            response_format=response_format,
            retries=0 if timeout_seconds else 3,
        )

    def stream_chat(self, messages: list[dict], *, max_tokens: int = 4096) -> Iterator[str]:
        """Yield provider text deltas; callers own persistence and final parsing."""
        if self._chat_fn is not None:
            raise ValueError("注入式 chat_fn 不支持流式调用")
        if self._session_factory is None:
            raise ValueError("AgentModels 未配置 session_factory，无法解析 QA 模型")
        from ..model_gateway.base import ChatRequest

        with self._session_factory() as db:
            resolved = self._resolve_model(db, "QA")
            self._last_model_key = resolved.model_config_id
            gateway = self._gateway_factory(resolved)
            model_name = resolved.model_name
            db.commit()
        yield from gateway.stream_chat(ChatRequest(model=model_name, messages=messages, max_tokens=max_tokens))

    def chat_with_tools(
        self,
        messages: list[dict],
        *,
        tools: list[GatewayTool],
        tool_choice: str = "auto",
        max_tokens: int = 4096,
    ) -> ChatResponse:
        """Structured model response for planning; preserves the text-only API."""
        if self._chat_fn is not None:
            raise ValueError("注入式 chat_fn 不支持工具调用响应，请注入结构化 gateway")
        if self._session_factory is None:
            raise ValueError("AgentModels 未配置 session_factory，无法解析 QA 模型")
        from ..model_gateway.base import ChatRequest

        with self._session_factory() as db:
            resolved = self._resolve_model(db, "QA")
            self._last_model_key = resolved.model_config_id
            gateway = self._gateway_factory(resolved)
            model_name = resolved.model_name
            db.commit()
        return gateway.chat(
            ChatRequest(
                model=model_name,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                max_tokens=max_tokens,
            )
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class AgentRuntimeContext:
    """每次 invoke 时构造的运行上下文（frozen，不进入 checkpoint）。"""

    session_factory: Callable[[], Session]
    retrieval_service_factory: Callable[[], RetrievalService]
    models: AgentModels
    settings: Settings
    tokenizer: TokenEstimator
    clock: Callable[[], datetime]
    # 单次 run 截止时刻（epoch 秒）；每次 Worker 重试重新起算
    deadline: float
    tool_registry: ToolRegistry
    tool_executor: ToolExecutor
    skill_catalog: tuple[dict, ...] = ()
    principal: PrincipalContext | None = None


def build_context(
    *,
    settings: Settings | None = None,
    session_factory: Callable[[], Session] | None = None,
    retrieval_service_factory: Callable[[], RetrievalService] | None = None,
    models: AgentModels | None = None,
    clock: Callable[[], datetime] | None = None,
    deadline: float | None = None,
    user_id: str | None = None,
) -> AgentRuntimeContext:
    """构造运行上下文。默认复用业务 session 工厂与检索服务工厂。"""
    from ..db.session import SessionLocal

    settings = settings or get_settings()
    session_factory = session_factory or SessionLocal
    retrieval_service_factory = retrieval_service_factory or build_retrieval_service
    clock = clock or _utc_now
    models = models or AgentModels(session_factory=session_factory)
    if deadline is None:
        deadline = clock().timestamp() + settings.agent_timeout_seconds
    tool_registry = build_default_tool_registry()
    skill_catalog: tuple[dict, ...] = ()
    principal: PrincipalContext | None = None
    # Admin toggles are read at run construction time, so changes take effect
    # without restarting workers. If the capability schema is unavailable
    # during an upgrade, retain the code-owned safe defaults.
    try:
        from .capability import load_enabled_capabilities

        with session_factory() as db:
            user, skill_catalog = load_enabled_capabilities(
                db, tool_registry, user_id=user_id,
            )
            if user is not None:
                principal = PrincipalContext(
                    user_id=str(user.id),
                    username=user.username,
                    display_name=user.display_name,
                    is_admin=bool(user.is_admin),
                    status=user.status,
                )
    except Exception:  # noqa: BLE001 — startup/upgrade fallback is safe
        pass
    tool_executor = ToolExecutor(
        tool_registry,
        policy=ToolPolicy(allow_write=settings.agent_write_tools_enabled),
    )
    return AgentRuntimeContext(
        session_factory=session_factory,
        retrieval_service_factory=retrieval_service_factory,
        models=models,
        settings=settings,
        tokenizer=TokenEstimator(),
        clock=clock,
        deadline=deadline,
        tool_registry=tool_registry,
        tool_executor=tool_executor,
        skill_catalog=skill_catalog,
        principal=principal,
    )
