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
  const classification = source.classification;
  const classifiedOutput = classification?.output ?? {};
  // 兼容历史数据/旧接口：数据库中的数组字段可能是 NULL。
  const classificationMetadata = (
    classification as {
      metadata?: {
        module_name?: string | null;
        business_topic?: string | null;
        summary?: string | null;
        keywords?: string[] | null;
      };
    } | null
  )?.metadata ?? {};
  const classificationKeywords = Array.isArray(classificationMetadata.keywords)
    ? classificationMetadata.keywords
    : [];
  const classificationMissingFields = Array.isArray(classification?.missing_fields)
    ? classification.missing_fields
    : [];
  const outputText = (key: string) => {
    const value = classifiedOutput[key];
    return value === null || value === undefined || value === "" ? "—" : String(value);
  };

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

      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="h6" sx={{ mb: 1 }}>
            分类结果
          </Typography>
          {!classification ? (
            <Typography variant="body2" color="text.secondary">
              当前版本尚未生成分类结果。完成分类任务后，这里会显示模型判断和提取的元数据。
            </Typography>
          ) : (
            <>
              <InfoRow label="相关性">
                <Stack direction="row" spacing={1} alignItems="center">
                  <Chip
                    size="small"
                    label={classification.relevance ?? "未判定"}
                    color={classification.relevance === "RELEVANT" ? "success" : classification.relevance === "UNCERTAIN" ? "warning" : "default"}
                    variant="outlined"
                  />
                  {classification.relevance_confidence !== null && (
                    <Typography variant="body2" color="text.secondary">
                      置信度 {(classification.relevance_confidence * 100).toFixed(1)}%
                    </Typography>
                  )}
                </Stack>
              </InfoRow>
              <InfoRow label="产品 / 版本">
                {outputText("product_code")} / {outputText("product_version_code")}
              </InfoRow>
              <InfoRow label="文档类型 / 产品形态">
                {outputText("document_type_code")} / {outputText("product_form_code")}
              </InfoRow>
              <InfoRow label="模块 / 业务主题">
                {classificationMetadata.module_name ?? "—"} / {classificationMetadata.business_topic ?? "—"}
              </InfoRow>
              <InfoRow label="摘要">
                {classificationMetadata.summary ?? outputText("summary")}
              </InfoRow>
              <InfoRow label="关键词">
                {classificationKeywords.length > 0 ? classificationKeywords.join("、") : "—"}
              </InfoRow>
              {classification.reason_summary && <InfoRow label="判定说明">{classification.reason_summary}</InfoRow>}
              {classificationMissingFields.length > 0 && (
                <InfoRow label="缺失字段">{classificationMissingFields.join("、")}</InfoRow>
              )}
            </>
          )}
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
