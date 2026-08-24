import { Chip } from "@mui/material";
import {
  SOURCE_STATUS_META,
  STAGE_META,
  TASK_STATUS_META,
  VERSION_STATUS_META,
  statusLabel,
  type StatusMeta,
} from "../types/statusMeta";

type StatusKind = "source" | "version" | "task" | "stage";

const META_BY_KIND: Record<StatusKind, Record<string, StatusMeta>> = {
  source: SOURCE_STATUS_META,
  version: VERSION_STATUS_META,
  task: TASK_STATUS_META,
  stage: STAGE_META,
};

interface StatusChipProps {
  value: string | null | undefined;
  kind: StatusKind;
}

/** 后端状态 → 统一 Chip 展示。 */
export function StatusChip({ value, kind }: StatusChipProps) {
  const meta = statusLabel(META_BY_KIND[kind], value);
  return <Chip label={meta.label} color={meta.color} variant="outlined" />;
}
