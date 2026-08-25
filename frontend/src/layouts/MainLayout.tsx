import { AppShell } from "../components/AppShell";
import { ConversationWorkspaceProvider } from "../conversations/ConversationWorkspaceContext";

/** 主应用布局：AppShell（侧边导航 + 顶栏 + 内容区），内容由路由 Outlet 填充。 */
export function MainLayout() {
  return (
    <ConversationWorkspaceProvider>
      <AppShell />
    </ConversationWorkspaceProvider>
  );
}
