/**
 * 知识来源 API。
 *
 * 对应后端：
 * - GET  /api/v1/knowledge-sources
 * - GET  /api/v1/knowledge-sources/{source_id}
 * - POST /api/v1/knowledge-sources/{source_id}/retry
 */
import { apiGet, apiPost } from "./client";
import type { ApiList } from "../types/api";
import type {
  KnowledgeSource,
  KnowledgeSourceDetail,
  SourceRetryResult,
} from "../types/documents";

export function listKnowledgeSources(params: { limit?: number; offset?: number } = {}): Promise<ApiList<KnowledgeSource> & { total: number }> {
  const q = new URLSearchParams({ limit: String(params.limit ?? 50), offset: String(params.offset ?? 0) });
  return apiGet<ApiList<KnowledgeSource> & { total: number }>(`/api/v1/knowledge-sources?${q}`);
}

export function getKnowledgeSource(sourceId: string): Promise<KnowledgeSourceDetail> {
  return apiGet<KnowledgeSourceDetail>(`/api/v1/knowledge-sources/${sourceId}`);
}

export function retryKnowledgeSource(sourceId: string): Promise<SourceRetryResult> {
  return apiPost<SourceRetryResult>(`/api/v1/knowledge-sources/${sourceId}/retry`);
}
