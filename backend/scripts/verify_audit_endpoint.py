"""验证开发库审计接口端到端可用（开发专用，建临时管理员验证后清理）。

用法：python scripts/verify_audit_endpoint.py（在 backend/ 下）
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")  # 读取开发库 DATABASE_URL

from sqlalchemy import text

from app.db.session import SessionLocal, engine


def main() -> None:
    # 1) 确认审计表为全字段结构
    with engine.connect() as conn:
        cols = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='platform' AND table_name='audit_logs' "
                "ORDER BY ordinal_position"
            )
        ).scalars().all()
        print(f"audit_logs 列数: {len(cols)}")
        print("列:", ", ".join(cols[:14]) + " ...")

    # 2) 建临时管理员与会话
    from app.auth import sessions
    from app.core.config import get_settings
    from app.db.models.user import User

    tmp_id = uuid4()
    with SessionLocal() as s:
        admin = User(id=tmp_id, display_name="临时验证管理员", status="ACTIVE", is_admin=True, created_source="ADMIN")
        s.add(admin)
        s.flush()
        token = sessions.create_session(s, admin.id, 24)
        s.commit()
        cookie = {get_settings().session_cookie_name: token}

    # 3) 走完整 API（带浏览器 Origin，验证 CORS 头）
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.get(
        "/api/v1/admin/audit-logs",
        cookies=cookie,
        headers={"Origin": "http://127.0.0.1:5173"},
    )
    print("GET /api/v1/admin/audit-logs ->", resp.status_code)
    print("access-control-allow-origin:", resp.headers.get("access-control-allow-origin"))
    if resp.status_code == 200:
        data = resp.json()["data"]
        print("items:", len(data["items"]), "has_more:", data["has_more"])
    else:
        print(resp.text)

    # 4) 清理临时管理员及其会话
    with SessionLocal() as s:
        s.execute(text("DELETE FROM auth.login_sessions WHERE user_id = :id"), {"id": tmp_id})
        s.execute(text("DELETE FROM auth.users WHERE id = :id"), {"id": tmp_id})
        s.commit()
    print("已清理临时管理员")


if __name__ == "__main__":
    main()
