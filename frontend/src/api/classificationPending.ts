/**
 * 待分类确认（人工确认）API（DD-19 §9，仅管理员）。
 *
 * 对应后端 app/classify/api_admin.py：
 * - GET   /api/v1/admin/classification-pending
 * - GET   /api/v1/admin/classification-pending/{version_id}
 * - POST  /api/v1/admin/classification-pending/{version_id}/confirm-relevant
 * - POST  /api/v1/admin/classification-pending/{version_id}/confirm-irrelevant
 * - POST  /api/v1/admin/classification-pending/{version_id}/reclassify
 */
import { apiGet, apiPost } from "./client";
import type { ApiList } from "../types/api";
import type {
  ConfirmIrrelevantBody,
  ConfirmRelevantBody,
  PendingClassification,
} from "../types/classificationPending";

const BASE = "/api/v1/admin/classification-pending";

export function listPendingClassification(): Promise<ApiList<PendingClassification>> {
  return apiGet<ApiList<PendingClassification>>(BASE);
}

export function getPendingClassificationDetail(
  versionId: string,
): Promise<PendingClassification> {
  return apiGet<PendingClassification>(`${BASE}/${versionId}`);
}

export function confirmRelevant(
  versionId: string,
  body: ConfirmRelevantBody,
): Promise<PendingClassification> {
  return apiPost<PendingClassification>(`${BASE}/${versionId}/confirm-relevant`, body);
}

export function confirmIrrelevant(
  versionId: string,
  body: ConfirmIrrelevantBody,
): Promise<PendingClassification> {
  return apiPost<PendingClassification>(`${BASE}/${versionId}/confirm-irrelevant`, body);
}

export function reclassifyPending(versionId: string): Promise<PendingClassification> {
  return apiPost<PendingClassification>(`${BASE}/${versionId}/reclassify`, {});
}
