/**
 * 会话与问答 API。
 *
 * 对应后端设计文档第 10～14 节（会话 / 提问回答 / 引用 / 反馈）。
 * 后端接口尚未实现，当前全部返回 Mock 数据（下方均有 MOCK 标注）。
 * 接入真实后端时保留函数签名，改写函数体即可；页面无需改动。
 */
import type { ApiList } from "../types/api";
import type {
  Answer,
  AnswerBlock,
  Citation,
  Conversation,
  FeedbackRating,
  Message,
  QueryFilters,
} from "../types/conversations";

export interface CreateConversationInput {
  title?: string;
  filters?: QueryFilters;
}

export interface CreateMessageResult {
  message_id: string;
  answer_id: string;
  status: string;
}

export interface FeedbackInput {
  rating: FeedbackRating;
  reason_codes?: string[];
  comment?: string;
}

export interface CatalogOption {
  id: string;
  name: string;
}

/**
 * 查询条件字典。
 * MOCK：后端 API-DICT-* 尚未实现，页面用固定字典，后续替换为
 * GET /api/v1/catalog/products、/products/{id}/versions、/document-types。
 */
export const CATALOG_OPTIONS = {
  products: [
    { id: "ae", name: "AE" },
    { id: "tda", name: "TDA" },
  ] as CatalogOption[],
  versions: {
    ae: [
      { id: "ae-v8", name: "V8 / 8.2" },
      { id: "ae-v7", name: "V7 / 7.0.3" },
      { id: "ae-v6", name: "V6 / 6.5.2" },
    ],
    tda: [
      { id: "tda-v3", name: "V3 / 3.1" },
      { id: "tda-v2", name: "V2 / 2.8" },
    ],
  } as Record<string, CatalogOption[]>,
  documentTypes: [
    { id: "spec", name: "产品规格" },
    { id: "feature", name: "产品功能" },
    { id: "whitepaper", name: "白皮书" },
    { id: "case", name: "SEG 案件" },
    { id: "deploy", name: "部署文档" },
  ] as CatalogOption[],
};

// ==================== MOCK 数据 ====================

const MOCK_DELAY_MS = 500;

function delay(ms = MOCK_DELAY_MS): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function newId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
}

const mockCitation: Citation = {
  citation_no: 1,
  document_title: "AE 硬件规格",
  document_type: "产品规格",
  heading_path: ["当前型号", "T90000 行"],
  version_label: "V8 / 8.2",
  source_updated_at: "2026-08-12T02:00:00+08:00",
  excerpt: "AMD EPYC 7H12，64 核 128 线程；内存 256GB；磁盘 16TB。",
  original_url: "#",
  availability: "AVAILABLE",
};

const mockAnswer: Answer = {
  id: "ans-1001",
  status: "SUCCEEDED",
  answer_type: "ANSWER",
  summary: "T90000 采用 AMD EPYC 7H12 处理器，配置 256GB 内存和 16TB 磁盘。",
  blocks: [
    {
      block_id: "b-1001-1",
      type: "paragraph",
      content: "处理器为 64 核 128 线程，当前规格表中的完整配置如下。",
      citation_nos: [1],
    },
    {
      block_id: "b-1001-2",
      type: "table",
      content: {
        columns: ["型号", "CPU", "核心 / 线程", "内存", "磁盘"],
        rows: [["T90000", "AMD EPYC 7H12", "64 核 / 128 线程", "256GB", "16TB"]],
      },
      citation_nos: [1],
    },
  ],
  citations: [mockCitation],
  degradation_flags: [],
  created_at: "2026-08-23T09:30:00+08:00",
  completed_at: "2026-08-23T09:30:05+08:00",
};

const mockMessages: Record<string, Message[]> = {
  "conv-1001": [
    {
      id: "msg-1001",
      conversation_id: "conv-1001",
      role: "user",
      content: "T90000 的 CPU、内存和磁盘配置是什么？",
      answer: null,
      created_at: "2026-08-23T09:30:00+08:00",
    },
    {
      id: "msg-1002",
      conversation_id: "conv-1001",
      role: "assistant",
      content: "",
      answer: mockAnswer,
      created_at: "2026-08-23T09:30:05+08:00",
    },
  ],
};

let mockConversations: Conversation[] = [
  {
    id: "conv-1001",
    title: "T90000 硬件规格",
    status: "ACTIVE",
    filters: { product_id: "ae", product_version_id: null, document_type_id: "spec" },
    last_message_at: "2026-08-23T09:30:05+08:00",
    created_at: "2026-08-23T09:28:00+08:00",
  },
  {
    id: "conv-1002",
    title: "国产化型号清单",
    status: "ACTIVE",
    filters: { product_id: "ae", product_version_id: null, document_type_id: null },
    last_message_at: "2026-08-22T16:40:00+08:00",
    created_at: "2026-08-22T16:35:00+08:00",
  },
  {
    id: "conv-1003",
    title: "网桥与路由模式区别",
    status: "ACTIVE",
    filters: { product_id: null, product_version_id: null, document_type_id: "deploy" },
    last_message_at: "2026-08-21T11:12:00+08:00",
    created_at: "2026-08-21T11:05:00+08:00",
  },
  {
    id: "conv-1004",
    title: "V7.0 部署方式",
    status: "ACTIVE",
    filters: { product_id: "ae", product_version_id: "ae-v7", document_type_id: "deploy" },
    last_message_at: "2026-08-19T14:22:00+08:00",
    created_at: "2026-08-19T14:20:00+08:00",
  },
  {
    id: "conv-1005",
    title: "白云机场历史案件",
    status: "ARCHIVED",
    filters: { product_id: null, product_version_id: null, document_type_id: "case" },
    last_message_at: "2026-08-15T10:00:00+08:00",
    created_at: "2026-08-15T09:55:00+08:00",
  },
];

function buildMockAnswer(question: string): Answer {
  // MOCK: 对任意追问生成“低依据”占位回答，用于演示低依据提示与流式占位。
  const now = new Date().toISOString();
  const blocks: AnswerBlock[] = [
    {
      block_id: newId("b"),
      type: "paragraph",
      content: `当前为 Mock 演示回答。知识库暂未检索到与“${question.trim()}”直接相关的文档片段，建议补充关键词或放宽检索条件后重试。`,
      citation_nos: [],
    },
  ];
  return {
    id: newId("ans"),
    status: "SUCCEEDED",
    answer_type: "LOW_EVIDENCE",
    summary: "未找到与该问题高度匹配的知识依据，以下为低置信度参考。",
    blocks,
    citations: [],
    degradation_flags: ["LOW_EVIDENCE"],
    created_at: now,
    completed_at: now,
  };
}

// ==================== API（MOCK 实现） ====================

export async function listConversations(): Promise<ApiList<Conversation>> {
  // MOCK: GET /api/v1/conversations
  await delay();
  return { items: [...mockConversations] };
}

export async function getConversation(conversationId: string): Promise<Conversation> {
  // MOCK: GET /api/v1/conversations/{id}
  await delay(300);
  const conversation = mockConversations.find((item) => item.id === conversationId);
  if (!conversation) {
    throw new Error("会话不存在或已删除。");
  }
  return { ...conversation };
}

export async function createConversation(input: CreateConversationInput): Promise<Conversation> {
  // MOCK: POST /api/v1/conversations
  await delay(400);
  const conversation: Conversation = {
    id: newId("conv"),
    title: input.title ?? "新会话",
    status: "ACTIVE",
    filters: input.filters ?? { product_id: null, product_version_id: null, document_type_id: null },
    last_message_at: null,
    created_at: new Date().toISOString(),
  };
  mockConversations = [conversation, ...mockConversations];
  return { ...conversation };
}

export async function getMessages(conversationId: string): Promise<ApiList<Message>> {
  // MOCK: GET /api/v1/conversations/{id}/messages
  await delay();
  return { items: mockMessages[conversationId] ?? [] };
}

export async function createMessage(
  conversationId: string,
  content: string,
  filters?: QueryFilters,
): Promise<CreateMessageResult> {
  // MOCK: POST /api/v1/conversations/{id}/messages
  await delay(400);
  const messageId = newId("msg");
  const answerId = newId("ans");
  const userMessage: Message = {
    id: messageId,
    conversation_id: conversationId,
    role: "user",
    content: content.trim(),
    answer: null,
    created_at: new Date().toISOString(),
  };
  const existing = mockMessages[conversationId] ?? [];
  mockMessages[conversationId] = [...existing, userMessage];
  const conversation = mockConversations.find((item) => item.id === conversationId);
  if (conversation) {
    conversation.last_message_at = userMessage.created_at;
    if (conversation.title === "新会话" && content.trim()) {
      conversation.title = content.trim().slice(0, 20);
    }
  }
  return { message_id: messageId, answer_id: answerId, status: "PENDING" };
}

export async function getAnswer(answerId: string): Promise<Answer> {
  // MOCK: GET /api/v1/answers/{id}
  await delay(300);
  return buildMockAnswer("当前问题");
}

export async function submitFeedback(_answerId: string, _input: FeedbackInput): Promise<void> {
  // MOCK: PUT /api/v1/answers/{id}/feedback
  await delay(200);
}

export function buildFollowUpAnswer(question: string): Answer {
  // MOCK: 页面在“流式生成”占位结束后追加该回答。
  return buildMockAnswer(question);
}

export function appendAssistantMessage(conversationId: string, answer: Answer): Message {
  const message: Message = {
    id: newId("msg"),
    conversation_id: conversationId,
    role: "assistant",
    content: "",
    answer,
    created_at: new Date().toISOString(),
  };
  const existing = mockMessages[conversationId] ?? [];
  mockMessages[conversationId] = [...existing, message];
  return message;
}
