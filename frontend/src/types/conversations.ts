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

/** 答案状态。 */
export type AnswerStatus =
  | "PENDING"
  | "UNDERSTANDING"
  | "RETRIEVING"
  | "RERANKING"
  | "GENERATING"
  | "VALIDATING"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELED";

/** 引用可用状态。 */
export type CitationAvailability =
  | "AVAILABLE"
  | "SOURCE_OFFLINE"
  | "SOURCE_DELETED"
  | "EXTERNAL_UNAVAILABLE";

/** 回答引用。 */
export interface Citation {
  citation_no: number;
  document_title: string;
  document_type: string | null;
  heading_path: string[];
  version_label: string | null;
  source_updated_at: string | null;
  excerpt: string | null;
  original_url: string | null;
  availability: CitationAvailability;
}

/** 回答内容块。 */
export interface AnswerBlock {
  block_id: string;
  type: "paragraph" | "table" | "list";
  content: string | { columns: string[]; rows: string[][] };
  citation_nos: number[];
}

/** 回答。 */
export interface Answer {
  id: string;
  status: AnswerStatus;
  answer_type: "ANSWER" | "NO_EVIDENCE" | "LOW_EVIDENCE";
  summary: string;
  blocks: AnswerBlock[];
  citations: Citation[];
  degradation_flags: string[];
  created_at: string | null;
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
