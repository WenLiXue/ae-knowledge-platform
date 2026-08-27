import { createBrowserRouter, Navigate } from "react-router-dom";
import { RequireAuth } from "../auth/AuthContext";
import { PlaceholderPage } from "../components/PlaceholderPage";
import { AuthLayout } from "../layouts/AuthLayout";
import { MainLayout } from "../layouts/MainLayout";
import { ConversationPage } from "../pages/ConversationPage";
import { DocumentDetailPage } from "../pages/DocumentDetailPage";
import { DocumentImportPage } from "../pages/DocumentImportPage";
import { DocumentsPage } from "../pages/DocumentsPage";
import { AuditLogsPage } from "../pages/admin/AuditLogsPage";
import { AgentCapabilitiesPage } from "../pages/admin/AgentCapabilitiesPage";
import { KnowledgeConfigPage } from "../pages/admin/KnowledgeConfigPage";
import { LlmConfigPage } from "../pages/admin/LlmConfigPage";
import { PendingClassificationPage } from "../pages/admin/PendingClassificationPage";
import { SystemLogsPage } from "../pages/admin/SystemLogsPage";
import { TasksPage } from "../pages/admin/TasksPage";
import { LoginPage } from "../pages/LoginPage";
import { SearchPage } from "../pages/SearchPage";

/**
 * 应用路由。
 * - /login 独立于主布局（公开页）。
 * - 业务页统一嵌套在 RequireAuth + MainLayout 下，未登录自动跳转登录页。
 * - 尚未实现的功能页使用 PlaceholderPage 占位，保证所有路由可访问。
 */
export const router = createBrowserRouter([
  {
    path: "/login",
    element: (
      <AuthLayout>
        <LoginPage />
      </AuthLayout>
    ),
  },
  {
    element: (
      <RequireAuth>
        <MainLayout />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Navigate to="/search" replace /> },
      { path: "search", element: <SearchPage /> },
      { path: "conversations/:conversationId", element: <ConversationPage /> },
      { path: "documents/import", element: <DocumentImportPage /> },
      { path: "documents", element: <DocumentsPage /> },
      { path: "documents/:sourceId", element: <DocumentDetailPage /> },
      {
        path: "diagnosis",
        element: (
          <PlaceholderPage
            title="问题诊断"
            description="根据故障现象、日志与配置信息，结合知识库辅助定位问题根因。"
          />
        ),
      },
      {
        path: "admin/agent-capabilities",
        element: <AgentCapabilitiesPage />,
      },
      {
        path: "admin/tasks",
        element: <TasksPage />,
      },
      {
        path: "admin/pending-classification",
        element: <PendingClassificationPage />,
      },
      {
        path: "admin/knowledge-config",
        element: <KnowledgeConfigPage />,
      },
      {
        path: "admin/llm-config",
        element: <LlmConfigPage />,
      },
      {
        path: "admin/system-logs",
        element: <SystemLogsPage />,
      },
      {
        path: "admin/users",
        element: <PlaceholderPage title="用户管理" description="管理系统用户、角色与飞书绑定。" />,
      },
      {
        path: "admin/audit-logs",
        element: <AuditLogsPage />,
      },
      {
        path: "settings/profile",
        element: <PlaceholderPage title="个人设置" description="修改个人资料、密码与登录偏好。" />,
      },
      { path: "*", element: <Navigate to="/search" replace /> },
    ],
  },
]);
