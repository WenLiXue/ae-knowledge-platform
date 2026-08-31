/**
 * 会话与问答 API（DD-08 §10-14、§12 SSE）。
 *
 * 已接入真实后端：会话 CRUD、提问、回答、反馈、取消、SSE 事件订阅。
 * SSE 通过 EventSource（同源 Cookie 认证），断线由浏览器自动重连；页面刷新后
 * 从 getMessages 恢复（含进行中回答的 assistant 消息）并重新订阅。
 */
import { apiGet, apiPost, apiPatch, apiPut, apiDelete, API_BASE_URL } from "./client";
import type { ApiList } from "../types/api";
import type {
  Answer,
  AgentApproval,
  AnswerBlock,
  AnswerType,
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
  events_url: string;
}

export interface FeedbackInput {
  rating: FeedbackRating;
  reason_codes?: string[];
  comment?: string;
}

/** 进行中回答的展示状态。 */
export interface StreamingAnswer {
  answer_id: string;
  status: string;
  progress_stage: string | null;
  answer_type: AnswerType | null;
  summary: string | null;
  draft_text?: string | null;
  blocks: AnswerBlock[];
  citations: Citation[];
  degradation_flags: string[];
}

export function listConversations(signal?: AbortSignal): Promise<ApiList<Conversation>> {
  return apiGet<ApiList<Conversation>>("/api/v1/conversations", signal);
}

export function getConversation(conversationId: string, signal?: AbortSignal): Promise<Conversation> {
  return apiGet<Conversation>(`/api/v1/conversations/${conversationId}`, signal);
}

export function createConversation(input: CreateConversationInput): Promise<Conversation> {
  return apiPost<Conversation>("/api/v1/conversations", input);
}

export function updateConversation(
  conversationId: string,
  input: { title?: string; filters?: QueryFilters },
): Promise<Conversation> {
  return apiPatch<Conversation>(`/api/v1/conversations/${conversationId}`, input);
}

export function deleteConversation(conversationId: string): Promise<void> {
  return apiDelete<void>(`/api/v1/conversations/${conversationId}`);
}

export function getMessages(conversationId: string, signal?: AbortSignal): Promise<ApiList<Message>> {
  return apiGet<ApiList<Message>>(`/api/v1/conversations/${conversationId}/messages`, signal);
}

export function createMessage(
  conversationId: string,
  content: string,
  filters?: QueryFilters,
): Promise<CreateMessageResult> {
  return apiPost<CreateMessageResult>(`/api/v1/conversations/${conversationId}/messages`, {
    content,
    filters,
  });
}

export function getAnswer(answerId: string): Promise<Answer> {
  return apiGet<Answer>(`/api/v1/answers/${answerId}`);
}

export function retryAnswer(answerId: string): Promise<CreateMessageResult> {
  return apiPost<CreateMessageResult>(`/api/v1/answers/${answerId}/retry`, {});
}

export function submitFeedback(
  answerId: string,
  input: FeedbackInput,
): Promise<{ answer_id: string; status: string }> {
  return apiPut(`/api/v1/answers/${answerId}/feedback`, input);
}

export function cancelAnswer(answerId: string): Promise<Answer> {
  return apiPost<Answer>(`/api/v1/answers/${answerId}/cancel`);
}

export function listAnswerApprovals(answerId: string): Promise<{ items: AgentApproval[] }> {
  return apiGet<{ items: AgentApproval[] }>(`/api/v1/answers/${answerId}/approvals`);
}

export function decideAnswerApproval(
  answerId: string,
  approvalId: string,
  decision: "APPROVED" | "REJECTED",
): Promise<{ approval_id: string; status: string; answer_id: string }> {
  return apiPost(`/api/v1/answers/${answerId}/approvals/${approvalId}/decision`, { decision });
}

export interface AnswerEventsHandlers {
  onSnapshot?: (answer: Answer) => void;
  onStatus?: (payload: { answer_id: string; status: string; progress_stage: string | null }) => void;
  onBlock?: (block: AnswerBlock) => void;
  onCitation?: (citation: Citation) => void;
  onDelta?: (payload: { answer_id: string; text: string }) => void;
  onDone?: (payload: { answer_id: string; status: string; answer_type: string }) => void;
  onEnd?: () => void;
}

/** 订阅回答 SSE 事件。返回清理函数（关闭连接）。断线后由页面刷新/重订阅恢复。 */
export function subscribeAnswerEvents(
  answerId: string,
  handlers: AnswerEventsHandlers,
): () => void {
  // 用 fetch + ReadableStream 手动解析 SSE：前端(5173)与 API(8000)跨端口=跨源，
  // EventSource 无法设置凭证（withCredentials 为只读 getter），fetch credentials:include
  // 与普通 API 调用一致、可携带会话 Cookie。
  let cancelled = false;
  const controller = new AbortController();

  const dispatch = (block: string) => {
    const eventName = block.match(/^event:\s*(.+)$/m)?.[1];
    const dataLine = block.split("\n").find((line) => line.startsWith("data:"));
    if (!eventName || !dataLine) return;
    const payload = JSON.parse(dataLine.slice(5).trim());
    if (eventName === "answer.snapshot") handlers.onSnapshot?.(payload);
    else if (eventName === "answer.status") handlers.onStatus?.(payload);
    else if (eventName === "answer.block") handlers.onBlock?.(payload);
    else if (eventName === "answer.citation") handlers.onCitation?.(payload);
    else if (eventName === "answer.delta") handlers.onDelta?.(payload);
    else if (eventName === "answer.done") handlers.onDone?.(payload);
  };

  void (async () => {
    try {
      const resp = await fetch(`${API_BASE_URL}/api/v1/answers/${answerId}/events`, {
        credentials: "include",
        signal: controller.signal,
      });
      if (!resp.ok || !resp.body) throw new Error(`SSE 连接失败（${resp.status}）`);
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (!cancelled) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx = buffer.indexOf("\n\n");
        while (idx !== -1) {
          dispatch(buffer.slice(0, idx));
          buffer = buffer.slice(idx + 2);
          idx = buffer.indexOf("\n\n");
        }
      }
    } catch (err) {
      if ((err as Error).name === "AbortError") return; // 主动取消/清理
      // 连接中断：不做自动重连，交由页面刷新或重新提问恢复
    } finally {
      if (!cancelled) handlers.onEnd?.();
    }
  })();

  return () => {
    cancelled = true;
    controller.abort();
  };
}

export function isInProgress(status: string): boolean {
  return status === "PENDING" || status === "WAITING" || status === "RETRIEVING" || status === "STREAMING";
}
