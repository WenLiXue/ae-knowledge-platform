"""日志上下文：请求 / 任务关联标识，经 ContextVar 注入每条日志记录。

- 请求上下文（request_id / ip / user_agent / user_id）由中间件与认证依赖写入；
- 任务上下文（task_id / attempt_no / task_type / source_id / version_id / worker_id）
  由 Worker 在单任务执行期间写入；
- ContextFilter 挂到日志 Handler 上，把两个上下文 + service 填充到每条 LogRecord，
  JSON formatter 与 DbLogHandler 都会读到这些字段。
- service 为模块级全局：API 进程默认 "api"，Worker 进程启动时设为 "worker"。
"""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass
class RequestContext:
    request_id: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    user_id: str | None = None


@dataclass
class TaskContext:
    task_id: str | None = None
    attempt_no: int | None = None
    task_type: str | None = None
    source_id: str | None = None
    version_id: str | None = None
    worker_id: str | None = None


_request_ctx: ContextVar[RequestContext] = ContextVar("log_request_ctx", default=RequestContext())
_task_ctx: ContextVar[TaskContext] = ContextVar("log_task_ctx", default=TaskContext())

# 进程级服务标识：API="api"，Worker="worker"
_service: str = "api"


def get_request_context() -> RequestContext:
    return _request_ctx.get()


def set_request_context(ctx: RequestContext) -> Token:
    return _request_ctx.set(ctx)


def reset_request_context(token: Token) -> None:
    _request_ctx.reset(token)


def set_user_id(user_id: str | None) -> None:
    """把当前请求上下文改为携带 user_id（仅同线程可见；跨线程请用 request.state）。"""
    ctx = _request_ctx.get()
    ctx.user_id = user_id
    _request_ctx.set(ctx)


def get_task_context() -> TaskContext:
    return _task_ctx.get()


def set_task_context(ctx: TaskContext) -> Token:
    return _task_ctx.set(ctx)


def reset_task_context(token: Token) -> None:
    _task_ctx.reset(token)


def set_service(service: str) -> None:
    global _service
    _service = service


class ContextFilter(logging.Filter):
    """把请求/任务上下文与 service 填充到每条日志记录（不覆盖 extra 已传值）。"""

    def filter(self, record: logging.LogRecord) -> bool:
        req = _request_ctx.get()
        task = _task_ctx.get()
        preset = {
            "request_id": req.request_id,
            "user_id": req.user_id,
            "ip": req.ip,
            "user_agent": req.user_agent,
            "task_id": task.task_id,
            "attempt_no": task.attempt_no,
            "task_type": task.task_type,
            "source_id": task.source_id,
            "version_id": task.version_id,
            "worker_id": task.worker_id,
        }
        for name, value in preset.items():
            if getattr(record, name, None) is None:
                setattr(record, name, value)
        if getattr(record, "service", None) is None:
            record.service = _service
        return True
