"""运行日志核心：结构化 JSON 输出、ERROR 级持久化、外部依赖调用日志。

- JsonFormatter / HumanFormatter：API 与 Worker 共用的输出格式（dev 人类可读，prod JSON）；
- setup_logging()：统一配置 root logger，幂等，供 API 与 Worker 各自启动时调用；
- DbLogHandler：把 ERROR+ 记录 best-effort 写入 platform.log_events（独立短事务，
  任何失败静默处理，绝不影响业务调用）；
- log_external_call()：外部依赖（飞书）调用记录 —— 只记依赖名/方法/路径/耗时/结果，
  绝不记录请求体、Authorization 头、Token 或密钥。

安全约束（DD-12 §7）：不得通过 extra 传 message/levelname/asctime（logging 会抛错）；
不得记录任何请求体、密钥或完整敏感正文。
"""

from __future__ import annotations

import json
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
import sys
import traceback
import uuid
from datetime import datetime, timezone

from . import context
from .config import Settings, get_settings

# 调用点可通过 extra 传入的字段白名单（其余一律丢弃，防止密钥/正文混入）
_EXTRA_FIELDS = (
    "error_code", "method", "path", "query", "status", "duration_ms",
    "dependency", "http_method", "result",
    "stage", "next_stage", "category", "code", "attempt", "max_attempts", "error_summary",
    # Agent 节点结构化日志（DD-21 §17.1）：只放行 ID/节点/耗时/计数，不放行正文与密钥
    "run_id", "answer_id", "conversation_id", "graph_version", "node", "operation",
    "step_count", "model_config_id", "retrieval_run_id", "degradation_flags",
    "terminated", "query_rewrite_count", "citation_repair_count",
    "input_token_count", "output_token_count",
    # 受控脱敏采样（agent_log_payloads=true 时）——放行提问与回答摘要，不放行证据正文/提示词/密钥
    "question", "answer", "answer_type", "evidence_count",
)
# JSON 行里展平的上下文字段顺序
_CONTEXT_FIELDS = (
    "request_id", "user_id", "ip", "user_agent",
    "task_id", "attempt_no", "task_type", "source_id", "version_id", "worker_id",
)
_configured = False


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _extra_dict(record: logging.LogRecord) -> dict:
    return {k: getattr(record, k) for k in _EXTRA_FIELDS if getattr(record, k, None) is not None}


class JsonFormatter(logging.Formatter):
    """每行一个 JSON 对象的结构化格式。"""

    def format(self, record: logging.LogRecord) -> str:
        out: dict = {
            "ts": _iso(record.created),
            "level": record.levelname,
            "logger": record.name,
            "service": getattr(record, "service", "api"),
            "message": record.getMessage(),
        }
        for name in _CONTEXT_FIELDS:
            value = getattr(record, name, None)
            if value is not None:
                out[name] = value
        out.update(_extra_dict(record))
        if record.exc_info and record.exc_info[0]:
            out["traceback"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False, default=str)


class HumanFormatter(logging.Formatter):
    """开发环境人类可读格式，附带 request_id/task_id 便于关联。

    Agent 结构化日志（DD-21 §17.1）：节点日志渲染 node/op/ms/step/run；
    运行开始/完成/失败日志渲染截断的提问/答案预览与 answer_type/error_code。
    """

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        tags = []
        rid = getattr(record, "request_id", None)
        tid = getattr(record, "task_id", None)
        if rid:
            tags.append(f"request_id={rid}")
        if tid:
            tags.append(f"task_id={tid}")

        def tag(key: str, label: str) -> None:
            value = getattr(record, key, None)
            if value is not None:
                tags.append(f"{label}={value}")

        node = getattr(record, "node", None)
        if node:  # agent_node_finished：节点执行详情
            tags.append(f"node={node}")
            for key, label in (("operation", "op"), ("duration_ms", "ms"), ("step_count", "step")):
                tag(key, label)
            tag("retrieval_run_id", "run")
            tag("error_code", "err")
        msg = record.getMessage()
        if msg in ("agent_run_start", "agent_answer_done", "agent_answer_failed"):
            # 受控调试采样：完整提问与回答摘要（agent_log_payloads=true 时才有）
            tag("question", "q")
            tag("answer", "a")
            tag("answer_type", "type")
            tag("error_code", "err")
            tag("evidence_count", "ev")
        return f"{base} {' '.join(tags)}".rstrip()


def resolve_log_json(settings: Settings) -> bool:
    if settings.log_json is not None:
        return settings.log_json
    return settings.environment == "production"


def setup_logging() -> None:
    """配置 root logger（幂等）。API 在模块导入时调用，Worker 在 main() 调用。"""
    global _configured
    if _configured:
        return
    settings = get_settings()
    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())

    for handler in list(root.handlers):
        root.removeHandler(handler)

    context_filter = context.ContextFilter()

    stream = logging.StreamHandler(sys.stdout)
    if resolve_log_json(settings):
        stream.setFormatter(JsonFormatter())
    else:
        fmt = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
        stream.setFormatter(HumanFormatter(fmt=fmt))
    stream.addFilter(context_filter)
    root.addHandler(stream)

    # Keep daily operational logs in the deployment-mounted /app/logs path so
    # operators do not need to inspect Docker's internal storage directory.
    log_dir = Path("/app/logs")
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = TimedRotatingFileHandler(
            log_dir / "application.log",
            when="midnight",
            interval=1,
            backupCount=14,
            encoding="utf-8",
            utc=True,
        )
        file_handler.setFormatter(JsonFormatter())
        file_handler.addFilter(context_filter)
        root.addHandler(file_handler)
    except OSError:
        # stdout remains the authoritative fallback if a deployment does not
        # provide a writable log mount.
        logging.getLogger(__name__).warning("file_logging_unavailable path=%s", log_dir)

    if settings.log_persist_errors:
        db_handler = DbLogHandler(level=logging.ERROR)
        db_handler.addFilter(context_filter)
        root.addHandler(db_handler)

    # 访问日志由 request_context_middleware 统一记录，屏蔽 uvicorn 自带 access 行避免重复
    logging.getLogger("uvicorn.access").propagate = False
    logging.getLogger("uvicorn.error").propagate = False

    _configured = True


def _uuid_or_none(value) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


class DbLogHandler(logging.Handler):
    """ERROR+ 记录 best-effort 写入 platform.log_events。

    使用独立短事务（自有 SessionLocal），不碰请求级 get_db 会话或 Worker 打开的事务；
    任何失败静默（handleError），日志写入失败绝不改变业务行为。
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            from ..db.models.log import LogEvent
            from ..db.session import SessionLocal

            session = SessionLocal()
            try:
                traceback_text = None
                if record.exc_info and record.exc_info[0]:
                    traceback_text = "".join(traceback.format_exception(*record.exc_info))
                session.add(
                    LogEvent(
                        service=(getattr(record, "service", None) or "api")[:16],
                        level=record.levelname[:16],
                        logger=record.name[:128],
                        message=record.getMessage()[:1024],
                        error_code=getattr(record, "error_code", None),
                        request_id=getattr(record, "request_id", None),
                        user_id=_uuid_or_none(getattr(record, "user_id", None)),
                        ip=getattr(record, "ip", None),
                        task_id=getattr(record, "task_id", None),
                        source_id=getattr(record, "source_id", None),
                        version_id=getattr(record, "version_id", None),
                        detail=_extra_dict(record),
                        traceback=traceback_text,
                    )
                )
                session.commit()
            except Exception:
                session.rollback()
            finally:
                session.close()
        except Exception:
            # 连 SessionLocal/模型导入都失败时走 handleError（只回写内部日志，不抛给调用方）
            self.handleError(record)


def log_external_call(
    *,
    dependency: str,
    method: str,
    path: str,
    duration_ms: float,
    status: int | None = None,
    result: str = "ok",
) -> None:
    """记录一次外部依赖调用（如飞书 API）。

    只记录依赖名、方法、路径、耗时与结果；绝不记录请求体、Authorization 头或 Token。
    status>=400 或 result != "ok" 时记 WARNING，否则 INFO。
    """
    level = logging.WARNING if (status is not None and status >= 400) or result != "ok" else logging.INFO
    logging.getLogger(f"app.integration.{dependency}").log(
        level,
        "external_call",
        extra={
            "dependency": dependency,
            "http_method": method,
            "path": path,
            "duration_ms": round(duration_ms, 3),
            "status": status,
            "result": result,
        },
    )
