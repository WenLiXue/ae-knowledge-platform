import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, text

from .audit.api import router as audit_router
from .auth.api import router as auth_router
from .classify.api_admin import router as classification_admin_router
from .config.api_admin import router as admin_config_router
from .config.api_public import router as catalog_router
from .core.logging import setup_logging
from .core.middleware import RequestContextMiddleware
from .db.session import SessionLocal, engine
from .feishu import router as feishu_router
from .knowledge_sources import router as knowledge_sources_router
from .llm.api import router as llm_config_router
from .llm.migration import ensure_llm_schema_v2
from .system_logs.api import router as logs_router

logger = logging.getLogger("app.error")


def _check_infrastructure() -> None:
    """启动时校验基础设施可用性（PostgreSQL）。

    数据库不可达时快速失败并给出清晰提示，避免运行期大量 500。
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        raise RuntimeError(
            "PostgreSQL 不可达：请确认数据库服务已启动，且 DATABASE_URL 配置正确。"
        ) from exc


def _migrate_llm_config() -> None:
    """启动时执行旧版 LLM 配置到 schema_version=2 的幂等迁移（DD-20 §12）。

    表尚未创建（首次迁移前）或迁移失败时仅记录告警，不阻断启动；
    后续首个写操作会再次触发迁移。已在主事务外使用独立短事务提交。
    """
    try:
        with SessionLocal() as session:
            if not inspect(session.get_bind()).has_table("config_revisions", schema="platform"):
                logger.warning("llm_config_migration_skipped config_revisions 表不存在")
                return
            if ensure_llm_schema_v2(session):
                session.commit()
                logger.info("llm_config_migration_done 旧版 LLM 配置已迁移到 schema_version=2")
    except Exception:
        logger.warning("llm_config_migration_failed 迁移失败，将在首个写操作时重试", exc_info=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    _check_infrastructure()
    _migrate_llm_config()
    yield


setup_logging()

app = FastAPI(
    title="AE Knowledge Platform API",
    version="0.1.0",
    description="产品知识智能平台后端 API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# 请求上下文 + 访问日志 + X-Request-ID；同时写 request.state.request_id 供审计关联（DD-17 §4.2）
app.add_middleware(RequestContextMiddleware)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """未预期异常统一记 ERROR（含堆栈并落库），返回稳定 500；4xx 走各自默认处理。"""
    logger.error(
        "unhandled_exception",
        exc_info=exc,
        extra={
            "path": request.url.path,
            "error_code": getattr(exc, "code", None) or "INTERNAL_ERROR",
            "user_id": getattr(request.state, "user_id", None),
        },
    )
    return JSONResponse(
        status_code=500,
        content={"detail": {"code": "INTERNAL_ERROR", "message": "服务内部错误"}},
    )


app.include_router(auth_router)
app.include_router(catalog_router)
app.include_router(admin_config_router)
app.include_router(classification_admin_router)
app.include_router(llm_config_router)
app.include_router(audit_router)
app.include_router(logs_router)
app.include_router(feishu_router)
app.include_router(knowledge_sources_router)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    """Return a lightweight liveness response for local and deployment checks."""

    return {"status": "ok", "service": "ae-knowledge-platform-api"}
