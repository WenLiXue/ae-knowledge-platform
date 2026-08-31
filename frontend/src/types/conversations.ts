/**
 * 会话、问答与引用类型。
 *
 * 与后端设计文档（08_后端API与SSE接口_V0.1.md）第 10～14 节对齐；
 * 当前后端尚未实现会话/问答接口，页面使用 Mock 数据，字段按文档契约预留。
 */

/** 会话状态。 */
export type ConversationStatus = "ACTIVE" | "ARCHIVED" | "DELETED";

/** 查询筛选条件。 */
export interface QueryFilters {
  product_id: string | null;
  product_version_id: string | null;
  document_type_id: string | null;
}

/** 会话。 */
export interface Conversation {
  id: string;
  title: string;
  status: ConversationStatus;
  filters: QueryFilters;
  last_message_at: string | null;
  created_at: string;
}

/** 答案主状态（DD-08 §11.2）。细阶段走 progress_stage，不扩散为不稳定业务状态。 */
export type AnswerStatus =
  | "PENDING"
  | "WAITING"
  | "RETRIEVING"
  | "STREAMING"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELED";

/** 细阶段（DD-19 §13.2）。 */
export type AnswerStage =
  | "UNDERSTANDING"
  | "RETRIEVING"
  | "RERANKING"
  | "GENERATING"
  | "VALIDATING";

export interface AgentApproval {
  id: string;
  status: "PENDING" | "APPROVED" | "REJECTED" | "EXPIRED";
  tool_name: string;
  impact_summary: { tool?: string; step_title?: string; risk?: string; summary?: string };
  expires_at: string;
  decided_at: string | null;
}

/** 最终结果类型（DD-10 §4）。 */
export type AnswerType =
  | "ANSWER"
  | "PARTIAL"
  | "CLARIFICATION"
  | "INSUFFICIENT"
  | "CONFLICT_WARNING";

/** 引用可用状态。 */
export type CitationAvailability =
  | "AVAILABLE"
  | "SOURCE_OFFLINE"
  | "SOURCE_DELETED"
  | "EXTERNAL_UNAVAILABLE";

/** 同一文档版本下的一个精确证据片段。 */
export interface CitationLocation {
  chunk_id: string | null;
  heading_path: string[];
  locator: Record<string, unknown>;
  excerpt: string | null;
}

/** 回答引用。 */
export interface Citation {
  citation_no: number;
  source_id: string | null;
  version_id: string | null;
  document_title: string;
  document_type: string | null;
  heading_path: string[];
  version_label: string | null;
  source_updated_at: string | null;
  excerpt: string | null;
  original_url: string | null;
  availability: CitationAvailability;
  /** 同一文档版本被多少个 chunk 支撑。 */
  support_count: number;
  locations: CitationLocation[];
}

/** 回答内容块。 */
export interface AnswerBlock {
  block_id: string;
  type: "paragraph" | "table" | "list" | "scope" | "warning" | "conflict";
  content: string | { columns: string[]; rows: string[][] };
  citation_nos: number[];
}

/** 回答。 */
export interface Answer {
  id: string;
  status: AnswerStatus;
  progress_stage?: AnswerStage | null;
  answer_type: AnswerType | null;
  summary: string | null;
  /** 流式生成期间的未校验草稿，终态后由正式答案替代。 */
  draft_text?: string | null;
  blocks: AnswerBlock[];
  citations: Citation[];
  degradation_flags: string[];
  error_code?: string | null;
  error_summary?: string | null;
  created_at: string;
  completed_at: string | null;
}

/** 会话消息。 */
export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  answer: Answer | null;
  created_at: string;
}

/** 反馈评分。 */
export type FeedbackRating = "HELPFUL" | "NOT_HELPFUL";
