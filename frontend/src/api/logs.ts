/**
 * 运行日志 API。
 *
 * 对应后端：
 * - GET  /api/v1/admin/system-logs（管理员，分页 + 组合筛选）
 */
import { apiGet } from "./client";
import type { SystemLogList } from "../types/logs";

export interface SystemLogQuery {
  level?: string;
  service?: string;
  request_id?: string;
  task_id?: string;
  source_id?: string;
  version_id?: string;
  user_id?: string;
  since?: string;
  until?: string;
  keyword?: string;
  limit?: number;
  offset?: number;
}

/** 分页查询运行日志。空值参数会被剔除，不进入 query string。 */
export function adminListSystemLogs(params: SystemLogQuery = {}): Promise<SystemLogList> {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      qs.set(key, String(value));
    }
  }
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return apiGet<SystemLogList>(`/api/v1/admin/system-logs${suffix}`);
}
