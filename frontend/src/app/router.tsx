import { createBrowserRouter, Navigate } from "react-router-dom";
import { RequireAdmin, RequireAuth } from "../auth/AuthContext";
import { PlaceholderPage } from "../components/PlaceholderPage";
import { AuthLayout } from "../layouts/AuthLayout";
import { MainLayout } from "../layouts/MainLayout";
import { ConversationPage } from "../pages/ConversationPage";
import { DocumentDetailPage } from "../pages/DocumentDetailPage";
import { DocumentImportPage } from "../pages/DocumentImportPage";
import { DocumentsPage } from "../pages/DocumentsPage";
import { KnowledgeConfigPage } from "../pages/admin/KnowledgeConfigPage";
import { LlmConfigPage } from "../pages/admin/LlmConfigPage";
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
        path: "admin/tasks",
        element: (
          <PlaceholderPage title="处理任务" description="查看文档入库处理任务列表及每个阶段的执行进度。" />
        ),
      },
      {
        path: "admin/pending-classification",
        element: (
          <PlaceholderPage title="待分类确认" description="人工确认文档分类结果，审核通过后进入向量化与索引。" />
        ),
      },
      {
        path: "admin/knowledge-config",
        element: (
          <RequireAdmin>
            <KnowledgeConfigPage />
          </RequireAdmin>
        ),
      },
      {
        path: "admin/llm-config",
        element: (
          <RequireAdmin>
            <LlmConfigPage />
          </RequireAdmin>
        ),
      },
      {
        path: "admin/users",
        element: (
          <RequireAdmin>
            <PlaceholderPage title="用户管理" description="管理系统用户、角色与飞书绑定。" />
          </RequireAdmin>
        ),
      },
      {
        path: "admin/audit-logs",
        element: (
          <RequireAdmin>
            <PlaceholderPage title="审计日志" description="查询登录、导入、配置变更等操作审计记录。" />
          </RequireAdmin>
        ),
      },
      {
        path: "settings/profile",
        element: <PlaceholderPage title="个人设置" description="修改个人资料、密码与登录偏好。" />,
      },
      { path: "*", element: <Navigate to="/search" replace /> },
    ],
  },
]);
