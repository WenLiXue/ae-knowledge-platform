/**
 * 操作审计类型（对齐后端 app/audit/schemas.py，DD-17）。
 */

export type AuditOutcome = "SUCCESS" | "FAILURE" | "DENIED";

export type AuditActorType = "USER" | "SYSTEM" | "WORKER" | "SERVICE";

export interface AuditLogListItem {
  id: string;
  occurred_at: string;
  actor_type: AuditActorType;
  actor_name: string;
  actor_account: string | null;
  module: string;
  action: string;
  outcome: AuditOutcome;
  error_code: string | null;
  summary: string;
  target_type: string | null;
  target_id: string | null;
  target_name: string | null;
  source_ip: string | null;
  request_id: string;
}

export interface AuditLogChange {
  field: string;
  before: unknown;
  after: unknown;
}

export interface AuditLogDetail extends AuditLogListItem {
  actor_user_id: string | null;
  actor_key: string | null;
  changes: AuditLogChange[];
  metadata: Record<string, unknown>;
  trace_id: string | null;
  causation_id: string | null;
  source_type: string;
  user_agent: string | null;
  prev_hash: string | null;
  record_hash: string;
}

export interface AuditLogSummary {
  total: number;
  by_module: Array<{ module: string; count: number }>;
  by_outcome: Array<{ outcome: AuditOutcome; count: number }>;
}

export type AuditExportStatus = "PENDING" | "RUNNING" | "READY" | "FAILED" | "EXPIRED";

export interface AuditExport {
  id: string;
  status: AuditExportStatus;
  row_count: number | null;
  error_code: string | null;
  filters: Record<string, unknown>;
  requested_at: string;
  completed_at: string | null;
  expires_at: string | null;
}

/** 查询筛选参数（与列表/导出接口对齐）。时间传 ISO 字符串。 */
export interface AuditQueryParams {
  start_at?: string;
  end_at?: string;
  module?: string;
  action?: string;
  outcome?: AuditOutcome;
  keyword?: string;
  cursor?: string;
  limit?: number;
}
