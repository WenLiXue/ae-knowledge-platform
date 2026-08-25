/**
 * LLM 模型管理与服务配置 API（DD-20 §9）。
 *
 * 对应后端（仅管理员）：
 * -      /api/v1/admin/llm-config/models（GET/POST/PATCH/{id}/enable|disable/test）
 * -      /api/v1/admin/llm-config/service-bindings（GET/PUT）
 */
import { apiGet, apiPatch, apiPost, apiPut } from "./client";
import type {
  LlmModel,
  LlmModelSaveInput,
  LlmModelTestInput,
  LlmModelTestResult,
  ServiceBindings,
  ServiceBindingsSaveInput,
} from "../types/config";

export interface LlmModelsList {
  revision: number | null;
  items: LlmModel[];
}

export function adminListModels(): Promise<LlmModelsList> {
  return apiGet<LlmModelsList>("/api/v1/admin/llm-config/models");
}

export function adminCreateModel(data: LlmModelSaveInput): Promise<LlmModel> {
  return apiPost<LlmModel>("/api/v1/admin/llm-config/models", data);
}

export function adminUpdateModel(id: string, data: Partial<LlmModelSaveInput>): Promise<LlmModel> {
  return apiPatch<LlmModel>(`/api/v1/admin/llm-config/models/${id}`, data);
}

export function adminSetModelEnabled(id: string, enabled: boolean): Promise<LlmModel> {
  return apiPost<LlmModel>(`/api/v1/admin/llm-config/models/${id}/${enabled ? "enable" : "disable"}`);
}

export function adminTestModel(data: LlmModelTestInput): Promise<LlmModelTestResult> {
  return apiPost<LlmModelTestResult>("/api/v1/admin/llm-config/models/test", data);
}

export function getServiceBindings(): Promise<ServiceBindings> {
  return apiGet<ServiceBindings>("/api/v1/admin/llm-config/service-bindings");
}

export function saveServiceBindings(data: ServiceBindingsSaveInput): Promise<ServiceBindings> {
  return apiPut<ServiceBindings>("/api/v1/admin/llm-config/service-bindings", data);
}
