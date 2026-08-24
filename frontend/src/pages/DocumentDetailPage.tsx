import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link as RouterLink, useNavigate, useParams } from "react-router-dom";
import { Alert, Box, Button, Card, CardContent, Chip, IconButton, Stack, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import RefreshIcon from "@mui/icons-material/Refresh";
import ReplayIcon from "@mui/icons-material/Replay";
import { getErrorMessage } from "../api/client";
import { getKnowledgeSource, retryKnowledgeSource } from "../api/knowledgeSources";
import { ErrorAlert } from "../components/ErrorAlert";
import { FullPageLoading } from "../components/LoadingState";
import { StatusChip } from "../components/StatusChip";
import { RESOURCE_TYPE_LABEL } from "../types/statusMeta";
import type { KnowledgeSourceDetail } from "../types/documents";

function formatTime(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("zh-CN", {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function InfoRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Stack direction="row" spacing={2} sx={{ py: 1, borderBottom: 1, borderColor: "divider" }}>
      <Typography variant="body2" color="text.secondary" sx={{ width: 140, flexShrink: 0 }}>
        {label}
      </Typography>
      <Box sx={{ minWidth: 0 }}>{children}</Box>
    </Stack>
  );
}

/** 文档详情页：来源信息、版本/任务状态、失败重试。 */
export function DocumentDetailPage() {
  const { sourceId } = useParams<{ sourceId: string }>();
  const navigate = useNavigate();

  const [source, setSource] = useState<KnowledgeSourceDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [retrying, setRetrying] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!sourceId) return;
    setLoading(true);
    setError(null);
    try {
      const detail = await getKnowledgeSource(sourceId);
      setSource(detail);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [sourceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleRetry = async () => {
    if (!source || retrying) return;
    setRetrying(true);
    setNotice(null);
    try {
      const result = await retryKnowledgeSource(source.source_id);
      setNotice(`已为重试创建任务（任务 ${result.task_id ?? "—"}），处理状态已刷新。`);
      await load();
    } catch (err) {
      setNotice(getErrorMessage(err, "重试失败，请稍后再试。"));
    } finally {
      setRetrying(false);
    }
  };

  if (loading) {
    return <FullPageLoading />;
  }

  if (error && !source) {
    return <ErrorAlert error={error} onRetry={() => void load()} title="加载失败" />;
  }

  if (!source) {
    return null;
  }

  const failed = source.status === "FAILED";

  return (
    <>
      <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 2 }}>
        <IconButton component={RouterLink} to="/documents" aria-label="返回文档列表">
          <ArrowBackIcon />
        </IconButton>
        <Box minWidth={0}>
          <Typography variant="h6" noWrap>
            {source.display_name}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            source_id：{source.source_id}
          </Typography>
        </Box>
      </Stack>

      {error && <ErrorAlert error={error} onRetry={() => void load()} title="刷新失败" />}
      {notice && (
        <Alert severity={notice.includes("失败") ? "error" : "info"} sx={{ mb: 2 }}>
          {notice}
        </Alert>
      )}

      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
            <Typography variant="h6">基本信息</Typography>
            <Stack direction="row" spacing={1}>
              <Button size="small" variant="outlined" startIcon={<RefreshIcon />} onClick={() => void load()} disabled={loading}>
                刷新
              </Button>
              {failed && (
                <Button size="small" variant="contained" startIcon={<ReplayIcon />} onClick={() => void handleRetry()} disabled={retrying}>
                  {retrying ? "重试中…" : "重试处理"}
                </Button>
              )}
            </Stack>
          </Stack>

          <InfoRow label="文档名称">{source.display_name}</InfoRow>
          <InfoRow label="来源类型">
            {source.resource_type ? (
              <Chip size="small" label={RESOURCE_TYPE_LABEL[source.resource_type] ?? source.resource_type} variant="outlined" />
            ) : (
              "—"
            )}
          </InfoRow>
          <InfoRow label="来源状态">
            <StatusChip value={source.status} kind="source" />
          </InfoRow>
          <InfoRow label="更新状态">{source.update_status || "—"}</InfoRow>
          <InfoRow label="提交时间">{formatTime(source.created_at)}</InfoRow>
        </CardContent>
      </Card>

      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="h6" sx={{ mb: 1 }}>
            版本与任务
          </Typography>
          <InfoRow label="当前版本">{source.current_version_id ?? source.version_id ?? "—"}</InfoRow>
          <InfoRow label="待确认版本">{source.pending_version_id ?? "—"}</InfoRow>
          <InfoRow label="版本状态">
            <StatusChip value={source.version_status} kind="version" />
          </InfoRow>
          <InfoRow label="处理任务">{source.task_id ?? "—"}</InfoRow>
          <InfoRow label="任务状态">
            <StatusChip value={source.task_status} kind="task" />
          </InfoRow>
          <InfoRow label="处理阶段">
            <StatusChip value={source.processing_stage} kind="stage" />
          </InfoRow>
        </CardContent>
      </Card>

      {(source.last_error_code || source.last_error_summary) && (
        <Alert severity="error">
          <Typography variant="body2" fontWeight={600}>
            最近错误{source.last_error_code ? `（${source.last_error_code}）` : ""}
          </Typography>
          {source.last_error_summary && (
            <Typography variant="body2" sx={{ mt: 0.5 }}>
              {source.last_error_summary}
            </Typography>
          )}
        </Alert>
      )}

      {failed && (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
          该来源处理失败，可点击“重试处理”重新进入流水线。
        </Typography>
      )}
    </>
  );
}
