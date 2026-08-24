/**
 * 飞书文档发现与提交 API。
 *
 * 对应后端：
 * - GET  /api/v1/feishu/connection
 * - GET  /api/v1/feishu/documents
 * - POST /api/v1/feishu/documents/submit
 */
import { apiGet, apiPost } from "./client";
import type { ApiList } from "../types/api";
import type {
  FeishuDocument,
  FeishuResourceType,
  FeishuSubmitItem,
  FeishuSubmitResult,
} from "../types/documents";

export interface FeishuConnection {
  connected: boolean;
  provider: string;
  display_name: string;
  mode: string;
}

export interface ListFeishuDocumentsParams {
  query?: string;
  resource_type?: FeishuResourceType[];
  limit?: number;
  page_token?: string;
}

export function getFeishuConnection(): Promise<FeishuConnection> {
  return apiGet<FeishuConnection>("/api/v1/feishu/connection");
}

export function listFeishuDocuments(
  params: ListFeishuDocumentsParams = {},
): Promise<ApiList<FeishuDocument>> {
  const search = new URLSearchParams();
  if (params.query) {
    search.set("query", params.query);
  }
  params.resource_type?.forEach((type) => search.append("resource_type", type));
  search.set("limit", String(params.limit ?? 50));
  if (params.page_token) {
    search.set("page_token", params.page_token);
  }
  const queryString = search.toString();
  return apiGet<ApiList<FeishuDocument>>(
    `/api/v1/feishu/documents${queryString ? `?${queryString}` : ""}`,
  );
}

export function submitFeishuDocuments(
  items: FeishuSubmitItem[],
): Promise<ApiList<FeishuSubmitResult>> {
  return apiPost<ApiList<FeishuSubmitResult>>("/api/v1/feishu/documents/submit", { items });
}
