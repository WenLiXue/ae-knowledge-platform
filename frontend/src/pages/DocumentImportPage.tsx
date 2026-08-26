import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  FormControl,
  InputLabel,
  Link,
  List,
  ListItem,
  ListItemText,
  MenuItem,
  Pagination,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import RefreshIcon from "@mui/icons-material/Refresh";
import { getFeishuConnection, listFeishuDocuments, submitFeishuDocuments } from "../api/feishu";
import { getErrorMessage } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import { ErrorAlert } from "../components/ErrorAlert";
import { LoadingState } from "../components/LoadingState";
import { PageHeader } from "../components/PageHeader";
import { RESOURCE_TYPE_LABEL } from "../types/statusMeta";
import type { FeishuDocument, FeishuResourceType, FeishuSubmitResult } from "../types/documents";

type Notice = { severity: "info" | "success" | "error"; text: string };

const TYPE_OPTIONS: FeishuResourceType[] = ["wiki", "docx"];

/** 文档导入页：飞书文档搜索、类型筛选、多选批量提交入库。 */
export function DocumentImportPage() {
  const [documents, setDocuments] = useState<FeishuDocument[]>([]);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<"" | FeishuResourceType>("");
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  // 云盘接口一次返回全部文件（无服务端分页 token），改用客户端分页控件逐页展示
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [statusFilter, setStatusFilter] = useState<"" | "submitted" | "pending">("");
  const [sortBy, setSortBy] = useState<"modified" | "title">("modified");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [docs, connection] = await Promise.all([
        listFeishuDocuments({ limit: 50 }),
        getFeishuConnection(),
      ]);
      setDocuments(docs.items);
      setConnected(connection.connected);
      setPage(1);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const visibleDocuments = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    const filtered = documents.filter((document) => {
      if (keyword && !document.title.toLowerCase().includes(keyword)) return false;
      if (typeFilter && document.resource_type !== typeFilter) return false;
      if (statusFilter === "submitted" && !document.submitted) return false;
      if (statusFilter === "pending" && document.submitted) return false;
      return true;
    });
    return [...filtered].sort((a, b) =>
      sortBy === "title"
        ? a.title.localeCompare(b.title, "zh-CN")
        : new Date(b.modified_at).getTime() - new Date(a.modified_at).getTime(),
    );
  }, [documents, query, typeFilter, statusFilter, sortBy]);

  // 客户端分页：标准 Pagination 控件，每页 pageSize 条
  const totalPages = Math.max(1, Math.ceil(visibleDocuments.length / pageSize));
  const shownDocuments = useMemo(
    () => visibleDocuments.slice((page - 1) * pageSize, page * pageSize),
    [visibleDocuments, page, pageSize],
  );

  // 筛选/排序/每页条数变化时回到第 1 页
  useEffect(() => {
    setPage(1);
  }, [query, typeFilter, statusFilter, sortBy, pageSize]);

  const toggleSelection = (token: string) => {
    setSelected((current) =>
      current.includes(token) ? current.filter((item) => item !== token) : [...current, token],
    );
  };

  // 当前页可勾选的文档（已提交的不参与全选）
  const selectableDocuments = useMemo(
    () => shownDocuments.filter((document) => !document.submitted),
    [shownDocuments],
  );
  const allVisibleSelected =
    selectableDocuments.length > 0 &&
    selectableDocuments.every((document) => selected.includes(document.resource_token));
  const someVisibleSelected = selectableDocuments.some((document) =>
    selected.includes(document.resource_token),
  );

  const toggleSelectAll = () => {
    if (allVisibleSelected) {
      const remove = new Set(selectableDocuments.map((document) => document.resource_token));
      setSelected((current) => current.filter((token) => !remove.has(token)));
    } else {
      setSelected((current) => {
        const set = new Set(current);
        selectableDocuments.forEach((document) => set.add(document.resource_token));
        return [...set];
      });
    }
  };

  const handleSubmit = async () => {
    if (submitting || selected.length === 0) return;
    setSubmitting(true);
    setNotice(null);
    try {
      const items = selected.map((token) => {
        const document = documents.find((item) => item.resource_token === token)!;
        return {
          client_item_id: token,
          resource_token: token,
          resource_type: document.resource_type,
          url: document.url,
        };
      });
      const result = await submitFeishuDocuments(items);
      const results = result.items as FeishuSubmitResult[];
      const created = results.filter((item) => !item.duplicate).length;
      const duplicated = results.filter((item) => item.duplicate).length;

      setDocuments((current) =>
        current.map((document) =>
          selected.includes(document.resource_token) ? { ...document, submitted: true } : document,
        ),
      );
      setSelected([]);

      let text = `已提交入库 ${created} 个文档，正在处理中。`;
      if (duplicated > 0) {
        text += ` 其中 ${duplicated} 个已存在，未重复入库。`;
      }
      setNotice({
        severity: duplicated > 0 && created === 0 ? "info" : "success",
        text,
      });
    } catch (err) {
      setNotice({ severity: "error", text: getErrorMessage(err, "文档提交失败，请稍后重试。") });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <PageHeader
        title="文档导入"
        description="搜索并批量提交飞书文档，提交后系统将读取正文并进入处理流水线。"
      />

      {error && <ErrorAlert error={error} onRetry={() => void load()} title="加载失败" />}
      {!connected && !loading && !error && (
        <Alert severity="info" sx={{ mb: 2 }}>
          飞书服务当前未连接，文档列表可能为空；请在后台配置飞书连接后刷新。
        </Alert>
      )}
      {notice && (
        <Alert severity={notice.severity} sx={{ mb: 2 }}>
          {notice.text}
        </Alert>
      )}

      <Card>
        <CardContent sx={{ p: { xs: 2, sm: 3 } }}>
          <Stack spacing={2}>
            <Stack
              direction={{ xs: "column", sm: "row" }}
              spacing={2}
              justifyContent="space-between"
              alignItems={{ xs: "stretch", sm: "center" }}
            >
              <Box>
                <Typography variant="h6">选择飞书文档</Typography>
                <Typography color="text.secondary" variant="body2" sx={{ mt: 0.5 }}>
                  只展示当前用户可见的文档元数据，提交后才会读取正文并进入处理流程。
                </Typography>
              </Box>
              <Button variant="contained" disabled={!selected.length || submitting} onClick={handleSubmit}>
                {submitting ? "提交中…" : `提交入库${selected.length ? `（${selected.length}）` : ""}`}
              </Button>
            </Stack>

            <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ flexWrap: "wrap" }}>
              <TextField
                size="small"
                label="搜索文档标题"
                placeholder="输入关键词筛选"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                sx={{ flexGrow: 1 }}
              />
              <FormControl size="small" sx={{ minWidth: { sm: 130 } }}>
                <InputLabel>文档类型</InputLabel>
                <Select
                  label="文档类型"
                  value={typeFilter}
                  onChange={(event) => setTypeFilter(event.target.value as "" | FeishuResourceType)}
                >
                  <MenuItem value="">全部类型</MenuItem>
                  {TYPE_OPTIONS.map((type) => (
                    <MenuItem key={type} value={type}>
                      {RESOURCE_TYPE_LABEL[type] ?? type}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <FormControl size="small" sx={{ minWidth: { sm: 120 } }}>
                <InputLabel>导入状态</InputLabel>
                <Select
                  label="导入状态"
                  value={statusFilter}
                  onChange={(event) =>
                    setStatusFilter(event.target.value as "" | "submitted" | "pending")
                  }
                >
                  <MenuItem value="">全部</MenuItem>
                  <MenuItem value="pending">待导入</MenuItem>
                  <MenuItem value="submitted">已提交</MenuItem>
                </Select>
              </FormControl>
              <FormControl size="small" sx={{ minWidth: { sm: 120 } }}>
                <InputLabel>排序</InputLabel>
                <Select
                  label="排序"
                  value={sortBy}
                  onChange={(event) => setSortBy(event.target.value as "modified" | "title")}
                >
                  <MenuItem value="modified">最近修改</MenuItem>
                  <MenuItem value="title">标题</MenuItem>
                </Select>
              </FormControl>
              <FormControl size="small" sx={{ minWidth: { sm: 110 } }}>
                <InputLabel>每页条数</InputLabel>
                <Select
                  label="每页条数"
                  value={pageSize}
                  onChange={(event) => setPageSize(Number(event.target.value))}
                >
                  <MenuItem value={5}>5 条</MenuItem>
                  <MenuItem value={10}>10 条</MenuItem>
                  <MenuItem value={20}>20 条</MenuItem>
                  <MenuItem value={50}>50 条</MenuItem>
                </Select>
              </FormControl>
              <Button variant="outlined" startIcon={<RefreshIcon />} onClick={() => void load()} disabled={loading}>
                刷新
              </Button>
            </Stack>
          </Stack>
        </CardContent>
      </Card>

      <Card sx={{ mt: 3 }}>
        <CardContent sx={{ p: { xs: 1, sm: 2 } }}>
          {loading ? (
            <Box sx={{ py: 3 }}>
              <LoadingState label="正在加载飞书文档…" />
            </Box>
          ) : visibleDocuments.length === 0 ? (
            <Box sx={{ py: 3 }}>
              <EmptyState
                title="未找到可导入的文档"
                description="调整搜索关键词或文档类型筛选后再试；若无任何文档，请先检查飞书连接。"
              />
            </Box>
          ) : (
            <>
              <Box sx={{ display: "flex", alignItems: "center", gap: 1, px: 1, pb: 0.5 }}>
                <Checkbox
                  checked={allVisibleSelected}
                  indeterminate={someVisibleSelected && !allVisibleSelected}
                  onChange={toggleSelectAll}
                  disabled={selectableDocuments.length === 0}
                  inputProps={{ "aria-label": "全选当前列表" }}
                />
                <Typography variant="body2" color="text.secondary">
                  全选当前页（可导入 {selectableDocuments.length} 条，已选 {selected.length} 条）
                </Typography>
              </Box>
              <List disablePadding>
                {shownDocuments.map((document) => (
                  <ListItem key={document.resource_token} disableGutters divider>
                    <Checkbox
                      checked={selected.includes(document.resource_token)}
                      disabled={document.submitted}
                      onChange={() => toggleSelection(document.resource_token)}
                    />
                    <ListItemText
                      primary={
                        document.url ? (
                          <Link
                            href={document.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            underline="hover"
                            color="primary"
                            sx={{ display: "inline-flex", alignItems: "center", gap: 0.5 }}
                          >
                            {document.title}
                            <OpenInNewIcon sx={{ fontSize: 16, color: "text.secondary" }} />
                          </Link>
                        ) : (
                          document.title
                        )
                      }
                      secondary={`${document.owner_name} · 最近修改 ${new Date(
                        document.modified_at,
                      ).toLocaleDateString("zh-CN")}`}
                    />
                    <Chip
                      size="small"
                      label={RESOURCE_TYPE_LABEL[document.resource_type] ?? document.resource_type}
                      variant="outlined"
                      sx={{ mr: 1 }}
                    />
                    <Chip
                      size="small"
                      label={document.submitted ? "已提交" : "待导入"}
                      color={document.submitted ? "success" : "default"}
                      variant={document.submitted ? "filled" : "outlined"}
                    />
                  </ListItem>
                ))}
              </List>
              {totalPages > 1 && (
                <Box sx={{ display: "flex", justifyContent: "center", pt: 2 }}>
                  <Pagination
                    count={totalPages}
                    page={page}
                    onChange={(_event, value) => setPage(value)}
                    color="primary"
                    showFirstButton
                    showLastButton
                  />
                </Box>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </>
  );
}
