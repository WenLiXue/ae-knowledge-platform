/**
 * API 通用类型与错误类型。
 *
 * 后端成功响应统一为 { data: ... }，列表统一为 { items: [...] }；
 * 错误响应为 { detail: { code, message } } 或 { detail: "..." }。
 */

/** 通用 API 错误，message 为可直接展示给用户的提示。 */
export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;

  constructor(status: number, message: string, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

/** 后端成功响应外壳。 */
export interface ApiEnvelope<T> {
  data: T;
  meta?: Record<string, unknown>;
}

/** 列表响应外壳。 */
export interface ApiList<T> {
  items: T[];
  next_cursor?: string | null;
  has_more?: boolean;
}
