from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .auth.api import router as auth_router
from .config.api_admin import router as admin_config_router
from .config.api_public import router as catalog_router
from .db.session import engine
from .feishu import router as feishu_router
from .knowledge_sources import router as knowledge_sources_router


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


@asynccontextmanager
async def lifespan(_: FastAPI):
    _check_infrastructure()
    yield


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

app.include_router(auth_router)
app.include_router(catalog_router)
app.include_router(admin_config_router)
app.include_router(feishu_router)
app.include_router(knowledge_sources_router)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    """Return a lightweight liveness response for local and deployment checks."""

    return {"status": "ok", "service": "ae-knowledge-platform-api"}
