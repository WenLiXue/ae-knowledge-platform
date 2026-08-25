/** 认证 API；飞书扫码使用后端生成授权地址和 HttpOnly Session。 */
import { apiGet, apiPost } from "./client";
import type { User } from "../types/auth";

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
