/** 认证 API；飞书扫码使用后端生成授权地址和 HttpOnly Session。 */
import { apiGet, apiPost } from "./client";
import type { User } from "../types/auth";

// MOCK: 固定返回的演示用户（允许任意非空账号密码登录）。
const MOCK_USER: User = {
  id: "00000000-0000-0000-0000-000000000001",
  username: "demo",
  display_name: "演示用户",
  role: "admin",
  feishu_bound: false,
};

const MOCK_DELAY_MS = 600;

export async function passwordLogin(username: string, password: string): Promise<User> {
  // MOCK: 模拟网络延迟与账号密码校验；真实实现调用 POST /api/v1/auth/password/login。
  await new Promise((resolve) => setTimeout(resolve, MOCK_DELAY_MS));
  if (!username.trim() || !password.trim()) {
    throw new Error("请输入账号和密码。");
  }
  return MOCK_USER;
}

export async function feishuLoginStart(): Promise<{ auth_url: string }> {
  const data = await apiPost<{ authorize_url: string; state: string }>("/api/v1/auth/feishu/start");
  return { auth_url: data.authorize_url };
}

export async function getCurrentUser(): Promise<User> {
  const data = await apiGet<{
    user_id: string;
    display_name: string;
    is_admin: boolean;
    feishu_bound: boolean;
  }>("/api/v1/auth/me");
  return {
    id: data.user_id,
    username: data.display_name,
    display_name: data.display_name,
    role: data.is_admin ? "admin" : "user",
    feishu_bound: data.feishu_bound,
  };
}

export async function logoutRequest(): Promise<void> {
  await apiPost<{ ok: boolean }>("/api/v1/auth/logout");
}
