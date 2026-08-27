/**
 * 待分类确认（人工确认）类型。
 *
 * 与后端 GET/POST /api/v1/admin/classification-pending/* 返回保持一致
 * （见 backend/app/classify/confirmation.py `_pending_item`）。
 */

/** 待确认列表项 / 详情。 */
export interface PendingClassification {
  source_id: string;
  source_name: string;
  source_type: string;
  canonical_key: string;
  version_id: string;
  version_no: number;
  /** 版本乐观锁版本号，确认相关/无关时必须回传。 */
  row_version: number;
  version_status: string;
  classification: PendingClassificationDetail | null;
}

export interface PendingClassificationDetail {
  relevance: string | null;
  relevance_confidence: number | null;
  reason_summary: string | null;
  missing_fields: string[];
  evidence: Array<Record<string, unknown>>;
  /** 模型候选完整输出（含 product_code 等建议值，供人工覆盖表单预填）。 */
  output: Record<string, unknown>;
  model_key: string | null;
  prompt_revision: number | null;
  input_builder_revision: number | null;
  config_revision: number | null;
  input_hash: string | null;
  created_at: string | null;
}

/** 确认相关载荷：字段留空（null）则沿用模型候选（DD-19 §9）。 */
export interface ConfirmRelevantBody {
  expected_row_version: number;
  product_code?: string | null;
  product_version_code?: string | null;
  document_type_code?: string | null;
  product_form_code?: string | null;
  is_domestic?: boolean | null;
  module_name?: string | null;
  business_topic?: string | null;
  summary?: string | null;
  keywords?: string[] | null;
}

/** 确认无关载荷：来源下线并记录原因。 */
export interface ConfirmIrrelevantBody {
  expected_row_version: number;
  reason?: string | null;
}
