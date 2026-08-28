/** 知识库配置与 LLM 配置类型（对应后端 /api/v1/catalog 与 /api/v1/admin）。 */

export interface CatalogItem {
  id: string;
  code: string;
  name: string;
  status: string;
  sort_order: number;
}

export interface ProductVersion {
  id: string;
  product_id: string;
  version_code: string;
  big_version: string | null;
  release_date: string | null;
  status: string;
  sort_order: number;
}

export interface DocumentType {
  id: string;
  code: string;
  name: string;
  description: string | null;
  status: string;
  sort_order: number;
}

export interface SourcePriority {
  source_code: string;
  display_name: string;
  priority: number;
  status: string;
}

// ---- LLM 模型管理与服务配置（DD-20） ----

export type LlmModelType = "CHAT" | "EMBEDDING" | "RERANK";
export type LlmProtocol = "openai-compatible" | "anthropic";

export interface LlmModel {
  id: string;
  name: string;
  model_type: LlmModelType;
  provider: string;
  protocol: LlmProtocol;
  base_url: string;
  model_name: string;
  embedding_dimension: number | null;
  normalize_embeddings: boolean | null;
  enabled: boolean;
  has_api_key: boolean;
  used_by: string[];
}

export interface LlmModelSaveInput {
  name: string;
  model_type: LlmModelType;
  provider: string;
  protocol: LlmProtocol;
  base_url: string;
  model_name: string;
  embedding_dimension?: number | null;
  normalize_embeddings?: boolean | null;
  api_key?: string | null;
  enabled: boolean;
  expected_revision: number | null;
}

export interface LlmModelTestInput {
  model_type: LlmModelType;
  provider: string;
  protocol: LlmProtocol;
  base_url: string;
  model_name: string;
  embedding_dimension?: number | null;
  normalize_embeddings?: boolean | null;
  api_key?: string | null;
  model_id?: string | null;
}

export interface LlmModelTestResult {
  ok: boolean;
  message: string;
  duration_ms: number;
  dimension?: number | null;
}

export type ServiceType = "QA" | "DOCUMENT_CLASSIFICATION" | "DOCUMENT_EMBEDDING" | "RETRIEVAL_RERANK";

export interface ServiceBinding {
  service_type: ServiceType;
  display_name: string;
  description: string;
  required: boolean;
  model: { id: string; name: string; model_name: string } | null;
}

export interface ServiceBindings {
  revision: number | null;
  services: ServiceBinding[];
  models: LlmModel[];
}

export interface ServiceBindingsSaveInput {
  expected_revision: number | null;
  bindings: Record<ServiceType, string | null>;
}
