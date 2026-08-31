/**
 * 后端状态枚举 → 前端展示映射。
 *
 * 来源 / 版本 / 任务 / 处理阶段 的状态值来自后端，前端统一在此维护
 * 中文标签与颜色，避免各页面各自硬编码。
 *
 * bg / fg 取自原型状态标签配色（styles.css）：
 * - 处理中 / 运行中：蓝底 #e6f4ff + #0958d9
 * - 待确认 / 重试：黄底 #fffbe6 + #874d00
 * - 成功 / 就绪：绿底 #f6ffed + #237804
 * - 失败：红底 #fff2f0 + #cf1322
 * - 中性（已下线 / 已取消等）：灰底 #f2f3f5 + #646a73
 */
export interface StatusMeta {
  label: string;
  bg: string;
  fg: string;
}

const INFO: StatusMeta = { label: "", bg: "#e6f4ff", fg: "#0958d9" };
const WARNING: StatusMeta = { label: "", bg: "#fffbe6", fg: "#874d00" };
const SUCCESS: StatusMeta = { label: "", bg: "#f6ffed", fg: "#237804" };
const ERROR: StatusMeta = { label: "", bg: "#fff2f0", fg: "#cf1322" };
const NEUTRAL: StatusMeta = { label: "", bg: "#f2f3f5", fg: "#646a73" };

/** 知识来源状态。 */
export const SOURCE_STATUS_META: Record<string, StatusMeta> = {
  PROCESSING: { ...INFO, label: "处理中" },
  PENDING_CONFIRMATION: { ...WARNING, label: "待确认" },
  QUERYABLE: { ...SUCCESS, label: "可查询" },
  FAILED: { ...ERROR, label: "失败" },
  OFFLINE: { ...NEUTRAL, label: "已下线" },
};

/** 文档版本状态。 */
export const VERSION_STATUS_META: Record<string, StatusMeta> = {
  CREATED: { ...NEUTRAL, label: "已创建" },
  PROCESSING: { ...INFO, label: "处理中" },
  PENDING_CONFIRMATION: { ...WARNING, label: "待确认" },
  READY: { ...SUCCESS, label: "就绪" },
  FAILED: { ...ERROR, label: "失败" },
  SUPERSEDED: { ...NEUTRAL, label: "已取代" },
};

/** 处理任务状态。 */
export const TASK_STATUS_META: Record<string, StatusMeta> = {
  PENDING: { ...NEUTRAL, label: "等待中" },
  RUNNING: { ...INFO, label: "运行中" },
  RETRY_WAIT: { ...WARNING, label: "等待重试" },
  SUCCEEDED: { ...SUCCESS, label: "成功" },
  FAILED: { ...ERROR, label: "失败" },
  CANCELED: { ...NEUTRAL, label: "已取消" },
};

/** 文档处理阶段（均为进行中）。 */
export const STAGE_META: Record<string, StatusMeta> = {
  FETCHING: { ...INFO, label: "抓取中" },
  PARSING: { ...INFO, label: "解析中" },
  CLASSIFYING: { ...INFO, label: "分类中" },
  CHUNKING: { ...INFO, label: "分块中" },
  EMBEDDING: { ...INFO, label: "向量化中" },
  INDEXING: { ...INFO, label: "索引中" },
  FINALIZING: { ...INFO, label: "收尾中" },
};

/** 审计执行结果。 */
export const AUDIT_OUTCOME_META: Record<string, StatusMeta> = {
  SUCCESS: { ...SUCCESS, label: "成功" },
  FAILURE: { ...ERROR, label: "失败" },
  DENIED: { ...WARNING, label: "拒绝" },
};

/** 审计导出任务状态。 */
export const AUDIT_EXPORT_META: Record<string, StatusMeta> = {
  PENDING: { ...NEUTRAL, label: "等待中" },
  RUNNING: { ...INFO, label: "生成中" },
  READY: { ...SUCCESS, label: "已就绪" },
  FAILED: { ...ERROR, label: "失败" },
  EXPIRED: { ...NEUTRAL, label: "已过期" },
};

/** 审计业务模块。 */
export const AUDIT_MODULE_LABEL: Record<string, string> = {
  AUTH: "登录/认证",
  CONFIG: "系统配置",
  AUDIT: "审计管理",
  KNOWLEDGE: "知识库",
  TASKING: "处理任务",
  USER: "用户管理",
  CONVERSATION: "会话管理",
};

/** 审计动作展示名；原始动作码仅在详情中保留。 */
export const AUDIT_ACTION_LABEL: Record<string, string> = {
  "auth.login": "登录",
  "auth.logout": "退出登录",
  "auth.feishu.bind": "绑定飞书账号",
  "auth.feishu.unbind": "解除飞书绑定",
  "user.query": "查询用户",
  "user.view": "查看用户详情",
  "user.update": "更新用户",
  "user.enable": "启用用户",
  "user.disable": "禁用用户",
  "user.role.change": "变更用户角色",
  "conversation.admin.list": "查看全部会话",
  "conversation.admin.view": "查看会话详情",
  "audit.query": "查询审计日志",
  "audit.view_detail": "查看审计详情",
  "audit.export": "导出审计日志",
};

export const AUDIT_TARGET_LABEL: Record<string, string> = {
  USER: "用户",
  CONVERSATION: "会话",
  AUDIT_LOG: "审计日志",
  AUDIT_EXPORT: "审计导出",
  LLM_CONFIG: "LLM 配置",
  LLM_MODEL: "LLM 模型",
};

/** 任务类型展示。 */
export const TASK_TYPE_META: Record<string, string> = {
  FETCH: "抓取",
  PARSE: "解析",
  CLASSIFY: "分类",
  CHUNK: "分块",
  EMBED: "向量化",
  INDEX: "索引",
  FINALIZE: "收尾",
};

/** 资源类型展示。 */
export const RESOURCE_TYPE_LABEL: Record<string, string> = {
  WIKI: "知识库",
  DOCX: "文档",
  SHEET: "电子表格",
  wiki: "知识库",
  docx: "文档",
  sheet: "电子表格",
  FILE: "文件附件",
  file: "文件附件",
};

/** 来源渠道展示；与资源格式（Wiki/文档/表格）分开。 */
export const SOURCE_TYPE_LABEL: Record<string, string> = {
  FEISHU: "飞书",
  MANUAL_UPLOAD: "上传文件",
};

/** 获取任意状态的中文标签（未收录时展示原值、中性配色）。 */
export function statusLabel(meta: Record<string, StatusMeta>, value: string | null | undefined): StatusMeta {
  const fallback: StatusMeta = { label: "未知状态", bg: NEUTRAL.bg, fg: NEUTRAL.fg };
  return (value && meta[value]) || fallback;
}
