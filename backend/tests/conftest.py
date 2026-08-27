"""pytest 集成测试基础设施。

- 使用独立测试库（默认 ae_knowledge_test），不污染开发数据；
- 每个测试会话从空库执行 Alembic 迁移（验证迁移本身）；
- 每个测试前清空全部业务表并重新播种系统默认用户。

依赖：本地 PostgreSQL 容器（见 docker-compose.yml）处于运行状态。
"""

from __future__ import annotations

import os
import tempfile

_DEFAULT_TEST_URL = (
    "postgresql+psycopg://ae_knowledge:ae_knowledge_dev@localhost:5432/ae_knowledge_test"
)
# 必须在导入任何 app 模块之前设置，让 app.db.session 引擎指向测试库。
# 不能使用 setdefault：容器服务会注入开发库 DATABASE_URL，setdefault 会
# 让测试意外连接并重建开发库。
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", _DEFAULT_TEST_URL)
# 测试环境强制使用 Fake 飞书实现（真实环境变量优先于 .env，隔离开发者本机的 real 配置）
os.environ["FEISHU_PROVIDER"] = "fake"
# 测试环境强制真实能力开关为 false（优先级高于 .env），避免 dev .env 的
# FEATURE_REAL_QA/INDEXING/CLASSIFICATION=true 污染测试库（测试库无 LLM 配置）；
# 需要真实路径的用例自行 monkeypatch 置 true。
os.environ["FEATURE_REAL_QA"] = "false"
os.environ["FEATURE_REAL_CLASSIFICATION"] = "false"
os.environ["FEATURE_REAL_INDEXING"] = "false"
# 测试强制关闭 Agent 图（避免读取 dev .env 的 AGENT_GRAPH_ENABLED=true）：
# 默认走旧问答编排；需要 Agent 路径的用例自行 monkeypatch 置 true。
os.environ["AGENT_GRAPH_ENABLED"] = "false"
os.environ["AGENT_LOG_PAYLOADS"] = "false"
# 审计导出文件写入系统临时目录，避免污染仓库
os.environ.setdefault(
    "AUDIT_EXPORT_DIR", os.path.join(tempfile.gettempdir(), "ae_audit_exports_test")
)

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

_SYSTEM_USER_ID = "11111111-1111-1111-1111-111111111111"


def _admin_engine():
    """连接维护库（postgres），用于重建测试数据库。"""
    url = os.environ["DATABASE_URL"]
    admin_url = url.rsplit("/", 1)[0] + "/postgres"
    return create_engine(admin_url, isolation_level="AUTOCOMMIT")


@pytest.fixture(scope="session", autouse=True)
def setup_test_database() -> None:
    """重建测试库并执行 Alembic 迁移到最新版本。"""
    admin = _admin_engine()
    dbname = os.environ["DATABASE_URL"].rsplit("/", 1)[-1]
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    admin.dispose()

    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")

    # 会话级初始化 LangGraph checkpoint（agent_runtime schema）。
    # 必须在任何开放事务之外调用：setup() 含 CREATE INDEX CONCURRENTLY，
    # 会阻塞等待所有活跃事务结束。
    from app.agent.runtime import ensure_checkpoint_schema

    ensure_checkpoint_schema()


@pytest.fixture(autouse=True)
def clean_tables(setup_test_database) -> None:
    """每个测试前清空业务表并恢复系统默认用户。"""
    from app.db.session import engine

    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE tasking.task_attempts, tasking.processing_tasks, "
                "knowledge.feishu_source_details, knowledge.document_versions, "
                "knowledge.knowledge_sources, "
                "knowledge.source_priorities, knowledge.product_forms, "
                "knowledge.document_types, knowledge.product_versions, knowledge.products, "
                "platform.secret_values, platform.config_revisions, "
                "platform.audit_exports, platform.audit_logs, "
                "platform.log_events, "
                "agent.agent_skills, agent.agent_mcp_servers, "
                "conversation.answer_feedback, conversation.answer_citations, "
                "conversation.answers, conversation.messages, conversation.conversations, "
                "conversation.conversation_memories, conversation.agent_runs, "
                "conversation.retrieval_candidates, conversation.retrieval_runs, "
                "auth.oauth_states, auth.login_sessions, auth.external_credentials, "
                "auth.external_identities, auth.users RESTART IDENTITY CASCADE"
            )
        )
        conn.execute(
            text(
                "INSERT INTO auth.users (id, username, display_name, status, is_admin, created_source) "
                f"VALUES ('{_SYSTEM_USER_ID}', 'system', '系统', 'ACTIVE', false, 'ADMIN')"
            )
        )
    yield
