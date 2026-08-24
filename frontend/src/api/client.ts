/**
 * 统一 HTTP 客户端。
 *
 * - API_BASE_URL 通过环境变量 VITE_API_BASE_URL 配置；
 * - 统一解包 { data } 响应；
 * - 统一处理 401/403/404/409/429/500 等状态码，映射为用户可读文案；
 * - 不把后端内部异常直接展示给用户（见 getErrorMessage）。
 */
import { ApiError, type ApiEnvelope } from "../types/api";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export { API_BASE_URL };

/** 状态码 → 用户可读兜底提示。 */
const STATUS_FALLBACK: Record<number, string> = {
  400: "请求参数有误，请检查后重试。",
  401: "登录已失效，请重新登录。",
  403: "没有权限执行该操作。",
  404: "请求的资源不存在。",
  409: "操作冲突，请刷新后重试。",
  422: "请求参数不符合要求。",
  429: "请求过于频繁，请稍后重试。",
  500: "服务暂时不可用，请稍后重试。",
  502: "上游服务异常，请稍后重试。",
  503: "服务暂不可用，请稍后重试。",
};

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
}

async function parseErrorPayload(response: Response): Promise<{ message: string; code?: string }> {
  let message = "";
  let code: string | undefined;
  try {
    const body = await response.json();
    const detail = body.detail;
    if (typeof detail === "string") {
      message = detail;
    } else if (detail && typeof detail === "object") {
      message = typeof detail.message === "string" ? detail.message : "";
      code = typeof detail.code === "string" ? detail.code : undefined;
    }
  } catch {
    // 非 JSON 错误体忽略
  }
  return { message, code };
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, signal } = options;

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError(0, "无法连接服务器，请检查网络后重试。");
  }

  if (!response.ok) {
    const { message, code } = await parseErrorPayload(response);
    throw new ApiError(
      response.status,
      message || STATUS_FALLBACK[response.status] || `请求失败（${response.status}）`,
      code,
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }
  const payload = (await response.json()) as ApiEnvelope<T>;
  return payload.data;
}

export function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  return request<T>(path, { method: "GET", signal });
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, { method: "POST", body });
}

export function apiPatch<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, { method: "PATCH", body });
}

export function apiDelete<T>(path: string): Promise<T> {
  return request<T>(path, { method: "DELETE" });
}

/** 把任意错误转换为可展示给用户的文案。 */
export function getErrorMessage(error: unknown, fallback = "操作失败，请稍后重试。"): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return fallback;
}
