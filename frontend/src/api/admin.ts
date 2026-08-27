/**
 * 系统管理 API。
 *
 * 管理端接口：任务（GET /api/v1/admin/tasks，DD-03）、审计日志等。
 */
import { apiGet } from "./client";

export interface AdminTask {
  task_id: string;
  task_type: string;
  status: string;
  stage: string | null;
  attempt_count: number;
  max_attempts: number;
  last_error_category: string | null;
  last_error_code: string | null;
  last_error_summary: string | null;
  source_id: string | null;
  source_name: string | null;
  version_id: string | null;
  priority: number;
  created_at: string | null;
}

export interface TaskListParams {
  task_type?: string;
  status?: string;
  keyword?: string;
  limit?: number;
  offset?: number;
}

export interface TaskListResult {
  items: AdminTask[];
  total: number;
  limit: number;
  offset: number;
}

export interface PendingClassificationItem {
  source_id: string;
  display_name: string;
  suggested_category: string;
  confidence: number;
  status: string;
}

export interface AdminUser {
  user_id: string;
  username: string;
  display_name: string;
  login_method: string;
  feishu_bound: boolean;
  enabled: boolean;
  created_at: string | null;
}

export interface AuditLogEntry {
  log_id: string;
  operator_name: string;
  action: string;
  object_type: string;
  object_key: string;
  result: string;
  detail: string | null;
  created_at: string | null;
}

export function listAdminTasks(params: TaskListParams = {}): Promise<TaskListResult> {
  const query = new URLSearchParams();
  if (params.task_type) query.set("task_type", params.task_type);
  if (params.status) query.set("status", params.status);
  if (params.keyword) query.set("keyword", params.keyword);
  query.set("limit", String(params.limit ?? 50));
  query.set("offset", String(params.offset ?? 0));
  const qs = query.toString();
  return apiGet<TaskListResult>(`/api/v1/admin/tasks${qs ? `?${qs}` : ""}`);
}
