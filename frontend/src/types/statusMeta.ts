/**
 * 后端状态枚举 → 前端展示映射。
 *
 * 来源 / 版本 / 任务 / 处理阶段 的状态值来自后端，前端统一在此维护
 * 中文标签与颜色，避免各页面各自硬编码。
 */
import type { ChipProps } from "@mui/material";

export interface StatusMeta {
  label: string;
  color: ChipProps["color"];
}

/** 知识来源状态。 */
export const SOURCE_STATUS_META: Record<string, StatusMeta> = {
  PROCESSING: { label: "处理中", color: "info" },
  PENDING_CONFIRMATION: { label: "待确认", color: "warning" },
  QUERYABLE: { label: "可查询", color: "success" },
  FAILED: { label: "失败", color: "error" },
  OFFLINE: { label: "已下线", color: "default" },
};

/** 文档版本状态。 */
export const VERSION_STATUS_META: Record<string, StatusMeta> = {
  CREATED: { label: "已创建", color: "default" },
  PROCESSING: { label: "处理中", color: "info" },
  PENDING_CONFIRMATION: { label: "待确认", color: "warning" },
  READY: { label: "就绪", color: "success" },
  FAILED: { label: "失败", color: "error" },
  SUPERSEDED: { label: "已取代", color: "default" },
};

/** 处理任务状态。 */
export const TASK_STATUS_META: Record<string, StatusMeta> = {
  PENDING: { label: "等待中", color: "default" },
  RUNNING: { label: "运行中", color: "info" },
  RETRY_WAIT: { label: "等待重试", color: "warning" },
  SUCCEEDED: { label: "成功", color: "success" },
  FAILED: { label: "失败", color: "error" },
  CANCELED: { label: "已取消", color: "default" },
};

/** 文档处理阶段。 */
export const STAGE_META: Record<string, StatusMeta> = {
  FETCHING: { label: "抓取中", color: "info" },
  PARSING: { label: "解析中", color: "info" },
  CLASSIFYING: { label: "分类中", color: "info" },
  CHUNKING: { label: "分块中", color: "info" },
  EMBEDDING: { label: "向量化中", color: "info" },
  INDEXING: { label: "索引中", color: "info" },
  FINALIZING: { label: "收尾中", color: "info" },
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
  wiki: "知识库",
  docx: "文档",
};

/** 获取任意状态的中文标签（未收录时展示原值）。 */
export function statusLabel(meta: Record<string, StatusMeta>, value: string | null | undefined): StatusMeta {
  const fallback: StatusMeta = { label: value || "未知", color: "default" };
  return (value && meta[value]) || fallback;
}
