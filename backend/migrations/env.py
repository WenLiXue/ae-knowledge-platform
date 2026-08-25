import logging
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

from app.core.config import get_settings
from app.db.base import Base
import app.db.models  # noqa: F401  加载全部模型到 metadata
import app.audit.models  # noqa: F401  加载审计模型到 metadata

# Alembic Config 对象
config = context.config

# 配置 Python 日志：root 已被应用配置（运行日志系统）时不覆盖，只按 alembic.ini 意图设置关键级别，
# 避免 alembic 迁移把应用日志配置整体清掉（测试环境会在迁移后继续依赖这些 handler）。
if config.config_file_name is not None and not logging.getLogger().handlers:
    fileConfig(config.config_file_name)
else:
    logging.getLogger("alembic").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

# 数据库连接统一取自应用配置（backend/.env 或环境变量），避免双份连接串
config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata

# 仅处理设计约定的逻辑 Schema，避免 autogenerate 干扰其他 schema
_MANAGED_SCHEMAS = {"auth", "conversation", "knowledge", "tasking", "platform"}


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    if type_ == "table":
        return obj.schema in _MANAGED_SCHEMAS
    return True


def run_migrations_offline() -> None:
    """Offline 模式：只生成 SQL，不连接数据库。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_object=include_object,
        compare_type=True,
        version_table_schema="public",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Online 模式：连接数据库执行迁移。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_object=include_object,
            compare_type=True,
            version_table_schema="public",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
