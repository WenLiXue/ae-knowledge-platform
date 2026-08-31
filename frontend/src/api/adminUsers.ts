import { apiGet, apiPatch } from "./client";

export interface AdminUser { id: string; username: string | null; display_name: string; email: string | null; status: "ACTIVE" | "DISABLED"; is_admin: boolean; created_source: string; created_at: string; }
export interface AdminUserDetail extends AdminUser { feishu: { bound: boolean; provider: string | null; tenant_key: string | null; external_user_id: string | null; open_id: string | null; union_id: string | null; bound_at: string | null; access_expires_at: string | null } }
export interface AdminConversation { id: string; title: string; status: string; filters: Record<string, unknown>; last_message_at: string | null; created_at: string; owner: { id: string; username: string | null; display_name: string }; }
export function listAdminUsers(params: { keyword?: string; status?: string; limit?: number; offset?: number } = {}) { const q = new URLSearchParams(); Object.entries(params).forEach(([k,v]) => v !== undefined && v !== "" && q.set(k,String(v))); return apiGet<{items: AdminUser[]; total: number}>(`/api/v1/admin/users?${q}`); }
export function updateAdminUser(id: string, body: Partial<Pick<AdminUser,"display_name"|"status"|"is_admin">>) { return apiPatch<AdminUser>(`/api/v1/admin/users/${id}`, body); }
export function getAdminUser(id: string) { return apiGet<AdminUserDetail>(`/api/v1/admin/users/${id}`); }
export function listAdminConversations(params: { keyword?: string; limit?: number; offset?: number } = {}) { const q = new URLSearchParams(); Object.entries(params).forEach(([k,v]) => v !== undefined && v !== "" && q.set(k,String(v))); return apiGet<{items: AdminConversation[]; total: number}>(`/api/v1/admin/conversations?${q}`); }
export function getAdminConversation(id: string) { return apiGet<{conversation: AdminConversation; messages: Array<{id:string; role:string; content:string; created_at:string; answer?: {summary?:string|null}}> }>(`/api/v1/admin/conversations/${id}`); }
