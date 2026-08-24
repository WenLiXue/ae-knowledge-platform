/**
 * 文档与知识来源相关类型。
 *
 * 字段与后端接口返回保持一致：
 * - GET /api/v1/feishu/documents
 * - POST /api/v1/feishu/documents/submit
 * - GET /api/v1/knowledge-sources
 * - GET /api/v1/knowledge-sources/{source_id}
 */

export type FeishuResourceType = "wiki" | "docx";

/** 飞书文档发现列表项。 */
export interface FeishuDocument {
  resource_token: string;
  title: string;
  resource_type: FeishuResourceType;
  modified_at: string;
  owner_name: string;
  submitted: boolean;
  source_id: string | null;
}

/** 批量提交请求项。 */
export interface FeishuSubmitItem {
  client_item_id: string;
  resource_token: string;
  resource_type: FeishuResourceType;
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
  resource_token: string | null;
  resource_type: string | null;
  display_name: string;
  status: string;
  update_status: string;
  version_id: string | null;
  version_status: string | null;
  task_id: string | null;
  task_status: string | null;
  created_at: string | null;
}

/** 知识来源详情（GET /knowledge-sources/{source_id}）。 */
export interface KnowledgeSourceDetail extends KnowledgeSource {
  current_version_id: string | null;
  pending_version_id: string | null;
  processing_stage: string | null;
  last_error_code: string | null;
  last_error_summary: string | null;
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
