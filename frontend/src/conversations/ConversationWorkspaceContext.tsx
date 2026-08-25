import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { listConversations } from "../api/conversations";
import type { Conversation } from "../types/conversations";

/**
 * 会话工作区共享状态。
 *
 * 职责：作为最近会话列表的唯一状态所有者，避免 AppShell / SearchPage
 * 各自调用 listConversations() 造成重复请求。
 *
 * 注意：Provider 挂载时不会主动请求数据。真正触发加载的是 AppShell 在
 * 进入查询工作区（/search、/conversations/*）时调用 refreshConversations()，
 * 因此管理页等非查询页面不会加载会话数据。SearchPage 在创建新会话后
 * 调用 refreshConversations() 刷新侧栏。
 */
export interface ConversationWorkspaceValue {
  conversations: Conversation[];
  loading: boolean;
  error: unknown;
  refreshConversations: () => Promise<void>;
}

const ConversationWorkspaceContext = createContext<ConversationWorkspaceValue | null>(null);

export function ConversationWorkspaceProvider({ children }: { children: ReactNode }) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const refreshConversations = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await listConversations();
      setConversations(result.items);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, []);

  const value = useMemo<ConversationWorkspaceValue>(
    () => ({ conversations, loading, error, refreshConversations }),
    [conversations, loading, error, refreshConversations],
  );

  return (
    <ConversationWorkspaceContext.Provider value={value}>
      {children}
    </ConversationWorkspaceContext.Provider>
  );
}

export function useConversationWorkspace(): ConversationWorkspaceValue {
  const context = useContext(ConversationWorkspaceContext);
  if (!context) {
    throw new Error("useConversationWorkspace 必须在 <ConversationWorkspaceProvider> 内使用。");
  }
  return context;
}
