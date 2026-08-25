"""审计服务：事件构造、脱敏、哈希链、查询与导出（DD-17 §4、§5、§6、§9）。

写入语义：
- 成功事件与业务变更共享同一 Session，由应用服务统一 commit，保证原子提交；
- 失败/拒绝事件在业务事务回滚后用独立短事务写入，不覆盖原始业务错误；
- 未知动作直接拒绝；字段按动作白名单过滤并递归脱敏。
"""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import json
import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import Select, func, select, text
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..db.models.user import User
from ..db.session import SessionLocal
from .context import AuditContext, actor_from_user
from .models import AuditExport, AuditLog
from .policy import clean_summary, filter_changes, get_spec, redact_metadata, sanitize_text

logger = logging.getLogger(__name__)

DEFAULT_MAX_LIMIT = 200
DEFAULT_LIMIT = 50
MAX_EXPORT_DAYS = 90
MAX_QUERY_DAYS = 90

ACTOR_SYSTEM = {
    "actor_type": "SYSTEM",
    "actor_user_id": None,
    "actor_key": "system",
    "actor_name": "系统",
    "actor_account": None,
}


class AuditError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass
class AuditEvent:
    """一次审计事件的语义：Actor + Source + Action + Target + Outcome + Change + Correlation。"""

    action: str
    summary: str
    actor: dict
    context: AuditContext
    outcome: str = "SUCCESS"
    target_type: str | None = None
    target_id: str | None = None
    target_name: str | None = None
    changes: list[dict] | None = None
    metadata: dict | None = None
    error_code: str | None = None
    causation_id: str | None = None


# ---- HMAC 哈希链 ----

def _hmac_key() -> bytes:
    return get_settings().audit_hmac_key.encode("utf-8")


def canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _chain_payload(row: AuditLog) -> dict:
    return {
        "id": str(row.id),
        "occurred_at": row.occurred_at.isoformat(),
        "actor_type": row.actor_type,
        "actor_user_id": str(row.actor_user_id) if row.actor_user_id else None,
        "actor_key": row.actor_key,
        "actor_name": row.actor_name,
        "actor_account": row.actor_account,
        "module": row.module,
        "action": row.action,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "target_name": row.target_name,
        "outcome": row.outcome,
        "error_code": row.error_code,
        "summary": row.summary,
        "changes": row.changes,
        "metadata": row.metadata_,
        "request_id": row.request_id,
        "trace_id": row.trace_id,
        "causation_id": str(row.causation_id) if row.causation_id else None,
        "source_type": row.source_type,
        "source_ip": str(row.source_ip) if row.source_ip else None,
        "user_agent": row.user_agent,
        "schema_version": row.schema_version,
        "prev_hash": row.prev_hash,
    }


def _hash_row(row: AuditLog, prev_hash: str | None) -> str:
    payload = _chain_payload(row)
    payload["prev_hash"] = prev_hash
    message = f"{prev_hash or ''}|{canonical_json(payload)}".encode("utf-8")
    return hmac.new(_hmac_key(), message, hashlib.sha256).hexdigest()


def _last_record_hash(session: Session) -> str | None:
    return session.execute(
        select(AuditLog.record_hash)
        .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
        .limit(1)
    ).scalar_one_or_none()


# ---- 事件写入 ----

def _build_row(event: AuditEvent) -> AuditLog:
    spec = get_spec(event.action)  # 未知动作抛出 UnknownActionError，拒绝写入
    context = event.context
    row = AuditLog(
        id=uuid.uuid4(),
        occurred_at=datetime.now(timezone.utc),
        actor_type=event.actor.get("actor_type", "SYSTEM"),
        actor_user_id=event.actor.get("actor_user_id"),
        actor_key=event.actor.get("actor_key"),
        actor_name=event.actor.get("actor_name") or "系统",
        actor_account=event.actor.get("actor_account"),
        module=spec.module,
        action=spec.action,
        target_type=event.target_type or spec.target_type,
        target_id=event.target_id,
        target_name=event.target_name,
        outcome=event.outcome,
        error_code=event.error_code,
        summary=clean_summary(event.summary) or spec.action,
        changes=filter_changes(spec, event.changes or []),
        metadata_=redact_metadata(event.metadata),
        request_id=context.request_id,
        trace_id=context.trace_id,
        causation_id=event.causation_id,
        source_type=context.source_type,
        source_ip=context.source_ip,
        user_agent=context.user_agent,
        schema_version=1,
    )
    return row


def _finalize(row: AuditLog, session: Session) -> AuditLog:
    """计算 prev_hash/record_hash 并加入会话。调用方负责 commit/flush。"""
    row.prev_hash = _last_record_hash(session)
    row.record_hash = _hash_row(row, row.prev_hash)
    session.add(row)
    return row


def record_success(session: Session, event: AuditEvent) -> AuditLog:
    """成功事件：与业务变更共享同一 Session，由应用服务统一 commit。"""
    event.outcome = "SUCCESS"
    return _finalize(_build_row(event), session)


def record_failure_independent(event: AuditEvent) -> AuditLog | None:
    """失败事件：独立短事务写入。写入失败不覆盖原始业务错误，仅输出安全日志。"""
    event.outcome = "FAILURE"
    return _record_independent(event)


def record_denied_independent(event: AuditEvent) -> AuditLog | None:
    """权限拒绝事件：独立短事务写入，不泄露目标详情。"""
    event.outcome = "DENIED"
    return _record_independent(event)


def _record_independent(event: AuditEvent) -> AuditLog | None:
    try:
        with SessionLocal() as s:
            row = _finalize(_build_row(event), s)
            s.commit()
            return row
    except Exception:  # noqa: BLE001 —— 失败审计不得掩盖原始错误
        logger.exception("audit_write_failure action=%s outcome=%s", event.action, event.outcome)
        return None


def user_actor(user: User) -> dict:
    return actor_from_user(user)


def build_changes(fields: dict[str, tuple[object, object]]) -> list[dict]:
    """由 {field: (before, after)} 构造字段级变更列表，仅保留发生变化的项。"""
    return [
        {"field": field, "before": before, "after": after}
        for field, (before, after) in fields.items()
        if before != after
    ]


def success_event(
    *,
    user: User | None,
    context: AuditContext,
    action: str,
    summary: str,
    target_type: str | None = None,
    target_id: str | None = None,
    target_name: str | None = None,
    changes: list[dict] | None = None,
    metadata: dict | None = None,
    causation_id: str | None = None,
) -> AuditEvent:
    """构造 SUCCESS 事件（登录用户）。actor 为空时使用 SYSTEM 快照。"""
    return AuditEvent(
        action=action,
        summary=summary,
        actor=user_actor(user) if user is not None else dict(ACTOR_SYSTEM),
        context=context,
        target_type=target_type,
        target_id=target_id,
        target_name=target_name,
        changes=changes,
        metadata=metadata,
        causation_id=causation_id,
    )


def failure_event(
    *,
    user: User | None,
    context: AuditContext,
    action: str,
    summary: str,
    error_code: str,
    target_type: str | None = None,
    target_id: str | None = None,
    target_name: str | None = None,
    metadata: dict | None = None,
) -> AuditEvent:
    return AuditEvent(
        action=action,
        summary=summary,
        actor=user_actor(user) if user is not None else dict(ACTOR_SYSTEM),
        context=context,
        target_type=target_type,
        target_id=target_id,
        target_name=target_name,
        error_code=error_code,
        metadata=metadata,
        outcome="FAILURE",
    )


def denied_event(
    *,
    user: User,
    context: AuditContext,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    target_name: str | None = None,
) -> AuditEvent:
    """构造 DENIED 事件：不携带目标详情，仅记录操作者与动作。"""
    return AuditEvent(
        action=action,
        summary=f"权限不足，拒绝执行 {action}",
        actor=user_actor(user),
        context=context,
        target_type=target_type,
        target_id=target_id,
        target_name=target_name,
        error_code="FORBIDDEN",
        outcome="DENIED",
    )


# ---- 查询 ----

def _sanitize_keyword(keyword: str) -> str:
    cleaned = sanitize_text(keyword, 128)
    return cleaned.replace("%", "").replace("_", "")


def _build_query_stmt(
    *,
    start_at: datetime | None,
    end_at: datetime | None,
    actor_user_id: str | None,
    module: str | None,
    action: str | None,
    target_type: str | None,
    target_id: str | None,
    outcome: str | None,
    keyword: str | None,
) -> Select:
    stmt = select(AuditLog)
    if start_at is not None:
        stmt = stmt.where(AuditLog.occurred_at >= start_at)
    if end_at is not None:
        stmt = stmt.where(AuditLog.occurred_at <= end_at)
    if actor_user_id:
        stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)
    if module:
        stmt = stmt.where(AuditLog.module == module)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if target_type:
        stmt = stmt.where(AuditLog.target_type == target_type)
    if target_id:
        stmt = stmt.where(AuditLog.target_id == target_id)
    if outcome:
        stmt = stmt.where(AuditLog.outcome == outcome)
    if keyword:
        kw = _sanitize_keyword(keyword)
        if kw:
            like = f"%{kw}%"
            stmt = stmt.where(
                func.lower(AuditLog.id.cast(text("text"))).ilike(like)
                | func.lower(AuditLog.actor_name).ilike(like)
                | func.lower(AuditLog.actor_account).ilike(like)
                | func.lower(AuditLog.target_name).ilike(like)
            )
    return stmt


def query_audit_logs(
    session: Session,
    *,
    start_at: datetime | None,
    end_at: datetime | None,
    actor_user_id: str | None,
    module: str | None,
    action: str | None,
    target_type: str | None,
    target_id: str | None,
    outcome: str | None,
    keyword: str | None,
    cursor: str | None,
    limit: int,
) -> tuple[list[AuditLog], str | None, bool]:
    limit = max(1, min(limit, DEFAULT_MAX_LIMIT))
    stmt = _build_query_stmt(
        start_at=start_at,
        end_at=end_at,
        actor_user_id=actor_user_id,
        module=module,
        action=action,
        target_type=target_type,
        target_id=target_id,
        outcome=outcome,
        keyword=keyword,
    )
    if cursor:
        cursor_occurred, cursor_id = _decode_cursor(cursor)
        stmt = stmt.where(
            (AuditLog.occurred_at < cursor_occurred)
            | ((AuditLog.occurred_at == cursor_occurred) & (AuditLog.id < cursor_id))
        )
    stmt = stmt.order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc()).limit(limit + 1)
    rows = list(session.execute(stmt).scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = _encode_cursor(rows[-1].occurred_at, rows[-1].id) if rows else None
    return rows, next_cursor, has_more


def _encode_cursor(occurred_at: datetime, record_id) -> str:
    raw = f"{occurred_at.isoformat()}|{record_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        occurred_iso, record_id = raw.split("|", 1)
        return datetime.fromisoformat(occurred_iso), uuid.UUID(record_id)
    except (ValueError, UnicodeDecodeError) as exc:
        raise AuditError("INVALID_CURSOR", "游标无效", status=400) from exc


def get_summary(session: Session, *, start_at: datetime, end_at: datetime) -> dict:
    by_module = session.execute(
        select(AuditLog.module, func.count().label("n"))
        .where(AuditLog.occurred_at >= start_at, AuditLog.occurred_at <= end_at)
        .group_by(AuditLog.module)
        .order_by(text("n DESC"))
    ).all()
    by_outcome = session.execute(
        select(AuditLog.outcome, func.count().label("n"))
        .where(AuditLog.occurred_at >= start_at, AuditLog.occurred_at <= end_at)
        .group_by(AuditLog.outcome)
    ).all()
    total = session.execute(
        select(func.count()).where(AuditLog.occurred_at >= start_at, AuditLog.occurred_at <= end_at)
    ).scalar_one()
    return {
        "total": total,
        "by_module": [{"module": m, "count": n} for m, n in by_module],
        "by_outcome": [{"outcome": o, "count": n} for o, n in by_outcome],
    }


def verify_hash_chain(session: Session, *, since: datetime | None = None) -> list[dict]:
    """校验哈希链，返回所有异常项（link 断裂 / hash 不匹配）。只读，不自动修复。"""
    stmt = select(AuditLog).order_by(AuditLog.occurred_at, AuditLog.id)
    if since is not None:
        stmt = stmt.where(AuditLog.occurred_at >= since)
    rows = list(session.execute(stmt).scalars().all())
    mismatches: list[dict] = []
    prev: AuditLog | None = None
    for row in rows:
        expected_prev = prev.record_hash if prev is not None else None
        if row.prev_hash != expected_prev:
            mismatches.append(
                {"id": str(row.id), "type": "link", "expected": expected_prev, "actual": row.prev_hash}
            )
        recomputed = _hash_row(row, row.prev_hash)
        if recomputed != row.record_hash:
            mismatches.append(
                {"id": str(row.id), "type": "hash", "expected": recomputed, "actual": row.record_hash}
            )
        prev = row
    return mismatches


# ---- 导出 ----

_EXPORT_COLUMNS = [
    "occurred_at", "event_id", "actor_type", "actor_name", "actor_account",
    "module", "action", "outcome", "error_code", "target_type", "target_id",
    "target_name", "summary", "changes", "request_id", "source_type", "source_ip",
]

_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: object) -> str:
    """公式注入防护：值以 = + - @ 或制表/回车开头时加单引号前缀。"""
    if value is None:
        return ""
    text_value = str(value)
    if text_value.startswith(_CSV_FORMULA_PREFIXES):
        return "'" + text_value
    return text_value


def _row_to_csv_values(row: AuditLog) -> list[str]:
    changes = json.dumps(row.changes, ensure_ascii=False, separators=(",", ":"))
    return [
        _csv_safe(row.occurred_at.isoformat()),
        _csv_safe(str(row.id)),
        _csv_safe(row.actor_type),
        _csv_safe(row.actor_name),
        _csv_safe(row.actor_account),
        _csv_safe(row.module),
        _csv_safe(row.action),
        _csv_safe(row.outcome),
        _csv_safe(row.error_code),
        _csv_safe(row.target_type),
        _csv_safe(row.target_id),
        _csv_safe(row.target_name),
        _csv_safe(row.summary),
        _csv_safe(changes),
        _csv_safe(row.request_id),
        _csv_safe(row.source_type),
        _csv_safe(row.source_ip),
    ]


def _write_csv(rows: list[AuditLog], path: Path) -> str:
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(_EXPORT_COLUMNS)
        for row in rows:
            writer.writerow(_row_to_csv_values(row))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest


def _export_dir() -> Path:
    root = Path(get_settings().audit_export_dir)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[2] / root  # backend/ 下
    root.mkdir(parents=True, exist_ok=True)
    return root


def create_export(session: Session, user: User, filters: dict, context: AuditContext) -> AuditExport:
    row = AuditExport(
        id=uuid.uuid4(),
        requested_by_user_id=user.id,
        status="PENDING",
        filters=filters,
    )
    session.add(row)
    session.flush()
    session.commit()
    thread = threading.Thread(
        target=_run_export, args=(str(row.id), filters), name=f"audit-export-{row.id}", daemon=True
    )
    thread.start()
    return row


def _run_export(export_id: str, filters: dict) -> None:
    with SessionLocal() as s:
        row = s.get(AuditExport, export_id)
        if row is None:
            return
        row.status = "RUNNING"
        s.commit()
        try:
            rows = _query_export_rows(s, filters)
            if len(rows) > get_settings().audit_export_max_rows:
                raise AuditError("EXPORT_TOO_LARGE", f"超过单次导出上限（{get_settings().audit_export_max_rows} 条）")
            path = _export_dir() / f"audit_{export_id}.csv"
            digest = _write_csv(rows, path)
            now = datetime.now(timezone.utc)
            row.status = "READY"
            row.row_count = len(rows)
            row.file_path = str(path)
            row.file_sha256 = digest
            row.completed_at = now
            row.expires_at = now + timedelta(hours=get_settings().audit_export_ttl_hours)
        except Exception as exc:  # noqa: BLE001
            logger.exception("audit_export_failed export_id=%s", export_id)
            row.status = "FAILED"
            row.error_code = getattr(exc, "code", "EXPORT_FAILED")
        s.commit()


def _query_export_rows(session: Session, filters: dict) -> list[AuditLog]:
    stmt = _build_query_stmt(
        start_at=_parse_ts(filters.get("start_at")),
        end_at=_parse_ts(filters.get("end_at")),
        actor_user_id=filters.get("actor_user_id"),
        module=filters.get("module"),
        action=filters.get("action"),
        target_type=filters.get("target_type"),
        target_id=filters.get("target_id"),
        outcome=filters.get("outcome"),
        keyword=filters.get("keyword"),
    )
    stmt = stmt.order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
    return list(session.execute(stmt).scalars().all())


def _parse_ts(value):
    if not value:
        return None
    return datetime.fromisoformat(value)


def get_export(session: Session, export_id: str) -> AuditExport:
    row = session.get(AuditExport, export_id)
    if row is None:
        raise AuditError("EXPORT_NOT_FOUND", "导出任务不存在", status=404)
    return row


def download_export(session: Session, export_id: str) -> tuple[AuditExport, Path]:
    row = get_export(session, export_id)
    if row.status != "READY" or not row.file_path:
        raise AuditError("EXPORT_NOT_READY", "导出尚未就绪", status=409)
    path = Path(row.file_path)
    if row.expires_at is not None and row.expires_at < datetime.now(timezone.utc):
        _expire_export(session, row, path)
        raise AuditError("EXPORT_EXPIRED", "导出文件已过期，请重新导出", status=410)
    if not path.exists():
        raise AuditError("EXPORT_FILE_MISSING", "导出文件不存在", status=410)
    return row, path


def _expire_export(session: Session, row: AuditExport, path: Path) -> None:
    row.status = "EXPIRED"
    session.commit()
    try:
        if path.exists():
            path.unlink()
    except OSError:
        logger.warning("audit_export_cleanup_failed path=%s", path)
