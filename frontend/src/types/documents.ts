/**
 * 文档与知识来源相关类型。
 *
 * 字段与后端接口返回保持一致：
 * - GET /api/v1/feishu/documents
 * - POST /api/v1/feishu/documents/submit
 * - GET /api/v1/knowledge-sources
 * - GET /api/v1/knowledge-sources/{source_id}
 */

export type FeishuResourceType = "wiki" | "docx" | "sheet";

/** 飞书文档发现列表项。 */
export interface FeishuDocument {
  resource_token: string;
  title: string;
  resource_type: FeishuResourceType;
  modified_at: string;
  owner_name: string;
  submitted: boolean;
  source_id: string | null;
  /** 飞书原文地址，可点击跳转 */
  url: string | null;
}

/** 批量提交请求项。 */
export interface FeishuSubmitItem {
  client_item_id: string;
  resource_token: string;
  resource_type: FeishuResourceType;
  url?: string | null;
}

/** 批量提交结果项。 */
export interface FeishuSubmitResult {
  client_item_id: string;
  resource_token: string;
  source_id: string;
  version_id: string | null;
  task_id: string | null;
  status: string;
  duplicate: boolean;
}

/** 来源状态。 */
export type SourceStatus =
  | "PROCESSING"
  | "PENDING_CONFIRMATION"
  | "QUERYABLE"
  | "FAILED"
  | "OFFLINE";

/** 版本状态。 */
export type VersionStatus =
  | "CREATED"
  | "PROCESSING"
  | "PENDING_CONFIRMATION"
  | "READY"
  | "FAILED"
  | "SUPERSEDED";

/** 任务状态。 */
export type TaskStatus =
  | "PENDING"
  | "RUNNING"
  | "RETRY_WAIT"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELED";

/** 文档处理阶段。 */
export type ProcessingStage =
  | "FETCHING"
  | "PARSING"
  | "CLASSIFYING"
  | "CHUNKING"
  | "EMBEDDING"
  | "INDEXING"
  | "FINALIZING";

/** 知识来源列表项。 */
export interface KnowledgeSource {
  source_id: string;
  /** 来源渠道：飞书或本地上传。 */
  source_type: string | null;
  resource_token: string | null;
  resource_type: string | null;
  /** 飞书原文地址；本地上传来源为空。 */
  original_url: string | null;
  display_name: string;
  status: string;
  update_status: string;
  version_id: string | null;
  version_status: string | null;
  task_id: string | null;
  task_status: string | null;
  created_at: string | null;
  classification: ClassificationSummary | ClassificationDetail | null;
}

export interface ClassificationSummary {
  relevance?: string | null;
  relevance_confidence?: number | null;
  product_code?: string | null;
  product_name?: string | null;
  product_version_code?: string | null;
  document_type_code?: string | null;
  document_type_name?: string | null;
  product_form_code?: string | null;
  is_domestic?: boolean | null;
  module_name?: string | null;
  business_topic?: string | null;
  keywords?: string[] | null;
  summary?: string | null;
}

/** 知识来源详情（GET /knowledge-sources/{source_id}）。 */
export interface KnowledgeSourceDetail extends KnowledgeSource {
  current_version_id: string | null;
  pending_version_id: string | null;
  processing_stage: string | null;
  last_error_code: string | null;
  last_error_summary: string | null;
  classification: ClassificationDetail | null;
}

export interface ClassificationDetail {
  relevance: string | null;
  relevance_confidence: number | null;
  reason_summary: string | null;
  missing_fields: string[] | null;
  evidence: Array<Record<string, unknown>>;
  output: Record<string, unknown>;
  model_key: string | null;
  config_revision: number | null;
  created_at: string | null;
  document_type_name?: string | null;
  document_type_code?: string | null;
  metadata: {
    product_id: string | null;
    product_version_id: string | null;
    document_type_id: string | null;
    product_form_id: string | null;
    module_name: string | null;
    business_topic: string | null;
    summary: string | null;
    keywords: string[] | null;
  };
}

/** 重试结果。 */
export interface SourceRetryResult {
  source_id: string;
  display_name: string;
  status: string;
  task_id: string | null;
  task_status: string | null;
  retry_created: boolean;
}
