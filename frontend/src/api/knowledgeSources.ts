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

export function listKnowledgeSources(): Promise<ApiList<KnowledgeSource>> {
  return apiGet<ApiList<KnowledgeSource>>("/api/v1/knowledge-sources");
}

export function getKnowledgeSource(sourceId: string): Promise<KnowledgeSourceDetail> {
  return apiGet<KnowledgeSourceDetail>(`/api/v1/knowledge-sources/${sourceId}`);
}

export function retryKnowledgeSource(sourceId: string): Promise<SourceRetryResult> {
  return apiPost<SourceRetryResult>(`/api/v1/knowledge-sources/${sourceId}/retry`);
}
