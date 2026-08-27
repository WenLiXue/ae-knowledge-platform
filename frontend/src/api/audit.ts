/**
 * 操作审计管理 API（后端 /api/v1/admin/audit-*，需要登录）。
 */
import { apiGet, apiPost, API_BASE_URL } from "./client";
import type { ApiList } from "../types/api";
import type {
  AuditExport,
  AuditLogDetail,
  AuditLogListItem,
  AuditLogSummary,
  AuditQueryParams,
} from "../types/audit";

function buildQuery(params: object): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, String(value));
    }
  }
  const qs = query.toString();
  return qs ? `?${qs}` : "";
}

/** 分页查询审计日志（游标在 params.cursor）。 */
export function listAuditLogs(params: AuditQueryParams = {}): Promise<ApiList<AuditLogListItem>> {
  return apiGet<ApiList<AuditLogListItem>>(
    `/api/v1/admin/audit-logs${buildQuery(params)}`,
  );
}

/** 时间窗口内的模块/结果计数概览。 */
export function getAuditSummary(startAt?: string, endAt?: string): Promise<AuditLogSummary> {
  return apiGet<AuditLogSummary>(
    `/api/v1/admin/audit-logs/summary${buildQuery({ start_at: startAt, end_at: endAt })}`,
  );
}

/** 单条审计详情（读取本身会被记录为 audit.view_detail）。 */
export function getAuditLogDetail(eventId: string): Promise<AuditLogDetail> {
  return apiGet<AuditLogDetail>(`/api/v1/admin/audit-logs/${eventId}`);
}

/** 创建异步导出任务（仅传筛选字段，不含分页参数）。 */
export function createAuditExport(data: AuditQueryParams): Promise<AuditExport> {
  const { start_at, end_at, module, action, outcome, keyword } = data;
  return apiPost<AuditExport>("/api/v1/admin/audit-exports", {
    start_at,
    end_at,
    module,
    action,
    outcome,
    keyword,
  });
}

/** 查询导出任务状态。 */
export function getAuditExport(exportId: string): Promise<AuditExport> {
  return apiGet<AuditExport>(`/api/v1/admin/audit-exports/${exportId}`);
}

/** 下载就绪的导出文件（Blob + 临时链接，凭证随 fetch 携带）。 */
export async function downloadAuditExport(exportId: string): Promise<void> {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/admin/audit-exports/${exportId}/download`,
    { credentials: "include" },
  );
  if (!response.ok) {
    let message = "下载失败，请稍后重试。";
    try {
      const body = (await response.json()) as { detail?: { message?: string } | string };
      if (body.detail && typeof body.detail === "object") {
        message = body.detail.message ?? message;
      } else if (typeof body.detail === "string") {
        message = body.detail;
      }
    } catch {
      /* 非 JSON 错误体忽略 */
    }
    throw new Error(message);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `audit_logs_${exportId}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
