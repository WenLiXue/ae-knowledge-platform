from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth.api import router as auth_router
from .feishu import router as feishu_router
from .knowledge_sources import router as knowledge_sources_router


app = FastAPI(
    title="AE Knowledge Platform API",
    version="0.1.0",
    description="产品知识智能平台后端 API",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(feishu_router)
app.include_router(knowledge_sources_router)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    """Return a lightweight liveness response for local and deployment checks."""

    return {"status": "ok", "service": "ae-knowledge-platform-api"}
