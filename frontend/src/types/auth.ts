/** 认证相关类型。 */

export type UserRole = "admin" | "user";

export interface User {
  id: string;
  username: string;
  display_name: string;
  role: UserRole;
  feishu_bound: boolean;
}
