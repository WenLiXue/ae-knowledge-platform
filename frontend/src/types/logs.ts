/** 运行日志类型（对应后端 GET /api/v1/admin/system-logs）。 */

export interface SystemLogItem {
  id: string;
  created_at: string;
  service: string;
  level: string;
  logger: string | null;
  message: string;
  error_code: string | null;
  request_id: string | null;
  user_id: string | null;
  ip: string | null;
  task_id: string | null;
  source_id: string | null;
  version_id: string | null;
  detail: Record<string, unknown>;
  traceback: string | null;
}

export interface SystemLogList {
  items: SystemLogItem[];
  total: number;
}
