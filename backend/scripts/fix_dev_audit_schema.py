"""修复开发库审计/日志表与迁移不一致（开发专用，勿在生产执行）。

背景：迁移 5e4fbd53f203 在落地后被重写（修订号不变），开发库仍停留在旧版
9 列 audit_logs；alembic 认为已应用、不会重放。本脚本（幂等，可重复跑）：

1. 丢弃 platform.audit_logs / audit_exports / log_events 三张可重建表
   （log_events 由外部迁移 1a2b3c4d5e6f 定义，但开发库版本链未记录该迁移，
   导致 upgrade head 重放时 DuplicateTable——统一重建最干净）；
2. 将 alembic 版本退回审计迁移前一版；
3. 干净重放：审计迁移（全字段）+ log_events 迁移；
4. 输出校验结果。

用法：python scripts/fix_dev_audit_schema.py（在 backend/ 下）
"""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.db.session import engine

PARENT_REVISION = "3a040f953e87"  # 审计迁移 5e4fbd53f203 的前一版


def main() -> None:
    # 1) 丢弃三张可重建表——无论上次失败后处于何种中间状态，都从干净状态重放
    with engine.begin() as conn:
        for table in ("platform.audit_logs", "platform.audit_exports", "platform.log_events"):
            conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
    print("已丢弃 audit_logs / audit_exports / log_events")

    cfg = Config("alembic.ini")
    # 2) 强制把版本退回审计迁移前一版（覆盖任何中间状态）
    command.stamp(cfg, PARENT_REVISION)
    print(f"alembic 版本已退回 {PARENT_REVISION}")
    # 3) 干净重放：审计迁移 + log_events 迁移
    command.upgrade(cfg, "head")
    print("alembic 已升级到 head")

    # 4) 校验
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        script = ScriptDirectory.from_config(cfg)
        current = ctx.get_current_revision()
        print(f"当前版本: {current}    head: {script.get_current_head()}")
        for table in ("platform.audit_logs", "platform.audit_exports", "platform.log_events"):
            try:
                conn.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))
                print(f"[ok] {table}")
            except Exception as exc:  # noqa: BLE001
                print(f"[缺失] {table}: {type(exc).__name__}")


if __name__ == "__main__":
    main()
