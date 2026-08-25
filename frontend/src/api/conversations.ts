/**
 * 会话与问答 API。
 *
 * 对应后端设计文档第 10～14 节（会话 / 提问回答 / 引用 / 反馈）。
 * 后端接口尚未实现，当前全部返回 Mock 数据（下方均有 MOCK 标注）。
 * 接入真实后端时保留函数签名，改写函数体即可；页面无需改动。
 */
import type { ApiList } from "../types/api";
import type {
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

// ==================== MOCK 数据 ====================

const MOCK_DELAY_MS = 500;

function delay(ms = MOCK_DELAY_MS): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function newId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
}

// 不再预置历史会话；列表只展示当前运行期间新建的会话。
const mockMessages: Record<string, Message[]> = {};
let mockConversations: Conversation[] = [];

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

export async function submitFeedback(_answerId: string, _input: FeedbackInput): Promise<void> {
  // MOCK: PUT /api/v1/answers/{id}/feedback
  await delay(200);
}
