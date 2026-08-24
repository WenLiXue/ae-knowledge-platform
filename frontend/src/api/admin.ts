/**
 * 系统管理 API。
 *
 * 管理端接口（任务 / 配置 / 用户 / 审计日志，API-TASK-* / API-CFG-* / API-USER-*）
 * 后端尚未实现，管理页面当前为占位状态。
 * 此模块先集中维护管理端数据类型；待后端就绪后再补充函数实现。
 */
import type { ApiList } from "../types/api";

export interface AdminTask {
  task_id: string;
  task_type: string;
  status: string;
  stage: string | null;
  attempt_count: number;
  last_error_summary: string | null;
  source_id: string | null;
  source_name: string | null;
  created_at: string | null;
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

export function listAdminTasks(_params?: Record<string, unknown>): Promise<ApiList<AdminTask>> {
  // TODO: 后端 API-TASK-001 就绪后实现。
  throw new Error("管理任务接口尚未实现。");
}
