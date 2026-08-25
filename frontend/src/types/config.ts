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
  major_version: number | null;
  minor_version: number | null;
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

export interface LlmConfig {
  provider: string;
  base_url: string;
  model: string;
  temperature: number;
  top_p: number;
  max_tokens: number;
  timeout_seconds: number;
  classification_model: string;
  embedding_model: string;
  enabled: boolean;
  has_api_key: boolean;
}

export interface LlmConfigSaveInput extends Omit<LlmConfig, "has_api_key"> {
  api_key?: string | null;
}
