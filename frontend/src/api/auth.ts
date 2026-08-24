/**
 * 认证 API。
 *
 * 后端认证接口（API-AUTH-*）尚未实现，当前为 Mock 登录。
 * 接入真实后端时仅需改写本文件中的函数实现，组件与页面无需改动。
 */
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
  // MOCK: 真实实现调用 POST /api/v1/auth/feishu/start 返回飞书授权地址。
  await new Promise((resolve) => setTimeout(resolve, MOCK_DELAY_MS));
  return { auth_url: "/mock/feishu/oauth" };
}

export async function logoutRequest(): Promise<void> {
  // MOCK: 真实实现调用 POST /api/v1/auth/logout。
  await new Promise((resolve) => setTimeout(resolve, 200));
}
