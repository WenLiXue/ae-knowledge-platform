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
  Select,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import RefreshIcon from "@mui/icons-material/Refresh";
import {
  getFeishuConnection,
  listFeishuDocuments,
  submitFeishuDocuments,
  submitFeishuLinks,
  uploadLocalDocuments,
} from "../api/feishu";
import { getErrorMessage } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import { ErrorAlert } from "../components/ErrorAlert";
import { LoadingState } from "../components/LoadingState";
import { ListPagination } from "../components/ListPagination";
import { PageHeader } from "../components/PageHeader";
import { RESOURCE_TYPE_LABEL } from "../types/statusMeta";
import type { FeishuDocument, FeishuResourceType, FeishuSubmitResult } from "../types/documents";

type Notice = { severity: "info" | "success" | "error"; text: string };
type ImportMode = "account" | "link" | "local";

const TYPE_OPTIONS: FeishuResourceType[] = ["wiki", "docx", "sheet"];

/** 文档导入页：飞书文档搜索、类型筛选、多选批量提交入库。 */
export function DocumentImportPage() {
  const [documents, setDocuments] = useState<FeishuDocument[]>([]);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [selectedDocuments, setSelectedDocuments] = useState<Record<string, FeishuDocument>>({});
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<"" | FeishuResourceType>("");
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  // 飞书接口使用 page_token；页面用游标历史实现可点击页码分页
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [pageCursors, setPageCursors] = useState<(string | null)[]>([null]);
  const [hasMore, setHasMore] = useState(false);
  const [statusFilter, setStatusFilter] = useState<"" | "submitted" | "pending">("");
  const [sortBy, setSortBy] = useState<"modified" | "title">("modified");
  const [importMode, setImportMode] = useState<ImportMode>("account");
  const [linkText, setLinkText] = useState("");
  const [localFiles, setLocalFiles] = useState<File[]>([]);
  const [directSubmitting, setDirectSubmitting] = useState(false);

  const load = useCallback(async (pageNo = 1, cursor: string | null = null) => {
    setLoading(true);
    setError(null);
    try {
      const [docs, connection] = await Promise.all([
        listFeishuDocuments({ limit: pageSize, query: query.trim() || undefined, resource_type: typeFilter ? [typeFilter] : undefined, page_token: cursor || undefined }),
        getFeishuConnection(),
      ]);
      setDocuments(docs.items);
      setConnected(connection.connected);
      setPage(pageNo);
      setHasMore(Boolean(docs.has_more ?? docs.next_cursor));
      if (pageNo === 1) setPageCursors([null]);
      if (docs.next_cursor) setPageCursors((current) => [...current.slice(0, pageNo), docs.next_cursor ?? null]);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [pageSize, query, typeFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const visibleDocuments = useMemo(() => {
    const filtered = documents.filter((document) => {
      if (statusFilter === "submitted" && !document.submitted) return false;
      if (statusFilter === "pending" && document.submitted) return false;
      return true;
    });
    return [...filtered].sort((a, b) =>
      sortBy === "title"
        ? a.title.localeCompare(b.title, "zh-CN")
        : new Date(b.modified_at).getTime() - new Date(a.modified_at).getTime(),
    );
  }, [documents, statusFilter, sortBy]);

  const totalPages = Math.max(1, page + (hasMore ? 1 : 0));
  const shownDocuments = visibleDocuments;

  const toggleSelection = (token: string) => {
    const document = documents.find((item) => item.resource_token === token);
    setSelected((current) =>
      current.includes(token) ? current.filter((item) => item !== token) : [...current, token],
    );
    if (document) {
      setSelectedDocuments((current) => {
        const next = { ...current };
        if (next[token]) delete next[token]; else next[token] = document;
        return next;
      });
    }
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
      setSelectedDocuments((current) => {
        const next = { ...current };
        remove.forEach((token) => delete next[token]);
        return next;
      });
    } else {
      setSelected((current) => {
        const set = new Set(current);
        selectableDocuments.forEach((document) => set.add(document.resource_token));
        return [...set];
      });
      setSelectedDocuments((current) => ({
        ...current,
        ...Object.fromEntries(selectableDocuments.map((document) => [document.resource_token, document])),
      }));
    }
  };

  const handleSubmit = async () => {
    if (submitting || selected.length === 0) return;
    setSubmitting(true);
    setNotice(null);
    try {
      const items = selected.map((token) => {
        const document = selectedDocuments[token]!;
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
      setSelectedDocuments({});

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

  const handleLinkSubmit = async () => {
    const urls = linkText.split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
    if (!urls.length || directSubmitting) return;
    setDirectSubmitting(true);
    setNotice(null);
    try {
      const result = await submitFeishuLinks(urls);
      const duplicated = result.items.filter((item) => item.duplicate).length;
      setNotice({
        severity: duplicated === result.items.length ? "info" : "success",
        text: `已提交 ${result.items.length - duplicated} 个飞书链接${duplicated ? `，${duplicated} 个已存在` : ""}。`,
      });
      setLinkText("");
    } catch (err) {
      setNotice({ severity: "error", text: getErrorMessage(err, "飞书链接提交失败。") });
    } finally {
      setDirectSubmitting(false);
    }
  };

  const handleLocalUpload = async () => {
    if (!localFiles.length || directSubmitting) return;
    setDirectSubmitting(true);
    setNotice(null);
    try {
      const result = await uploadLocalDocuments(localFiles);
      const duplicated = result.items.filter((item) => item.duplicate).length;
      setNotice({
        severity: duplicated === result.items.length ? "info" : "success",
        text: `已上传 ${result.items.length - duplicated} 个文件${duplicated ? `，${duplicated} 个内容重复` : ""}。`,
      });
      setLocalFiles([]);
    } catch (err) {
      setNotice({ severity: "error", text: getErrorMessage(err, "本地文件上传失败。") });
    } finally {
      setDirectSubmitting(false);
    }
  };

  return (
    <>
      <PageHeader
        title="文档导入"
        description="从当前飞书账号、飞书链接或本地文件导入知识，统一进入处理流水线。"
      />

      <Card sx={{ mb: 2 }}>
        <Tabs
          value={importMode}
          onChange={(_event, value: ImportMode) => {
            setImportMode(value);
            setNotice(null);
          }}
          aria-label="选择文档导入方式"
        >
          <Tab value="account" label="当前账号文档" />
          <Tab value="link" label="飞书链接" />
          <Tab value="local" label="本地文件" />
        </Tabs>
      </Card>

      {importMode === "account" && error && <ErrorAlert error={error} onRetry={() => void load()} title="加载失败" />}
      {importMode === "account" && !connected && !loading && !error && (
        <Alert severity="info" sx={{ mb: 2 }}>
          飞书服务当前未连接，文档列表可能为空；请在后台配置飞书连接后刷新。
        </Alert>
      )}
      {notice && (
        <Alert severity={notice.severity} sx={{ mb: 2 }}>
          {notice.text}
        </Alert>
      )}

      {importMode === "link" && (
        <Card>
          <CardContent sx={{ p: { xs: 2, sm: 3 } }}>
            <Typography variant="h6">通过飞书链接导入</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, mb: 2 }}>
              每行粘贴一个 Wiki 或文档链接。系统会使用当前账号的飞书授权读取内容。
            </Typography>
            <TextField
              multiline
              minRows={5}
              fullWidth
              value={linkText}
              onChange={(event) => setLinkText(event.target.value)}
              placeholder={"https://example.feishu.cn/wiki/...\nhttps://example.feishu.cn/sheets/..."}
              inputProps={{ "aria-label": "飞书文档链接" }}
            />
            <Stack direction="row" justifyContent="flex-end" sx={{ mt: 2 }}>
              <Button variant="contained" disabled={!linkText.trim() || directSubmitting} onClick={() => void handleLinkSubmit()}>
                {directSubmitting ? "解析提交中…" : "解析并提交"}
              </Button>
            </Stack>
          </CardContent>
        </Card>
      )}

      {importMode === "local" && (
        <Card>
          <CardContent sx={{ p: { xs: 2, sm: 3 } }}>
            <Typography variant="h6">上传本地文件</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
              支持 PDF、DOCX、XLSX；单个文件不超过 50 MB，每次最多 20 个。内容相同的文件会自动去重。
            </Typography>
            <Box
              sx={{ mt: 2, p: 4, border: 1, borderStyle: "dashed", borderColor: "divider", borderRadius: 2, textAlign: "center", bgcolor: "grey.50" }}
            >
              <Button component="label" variant="outlined">
                选择文件
                <input
                  hidden
                  type="file"
                  multiple
                  accept=".pdf,.docx,.xlsx"
                  onChange={(event) => setLocalFiles(Array.from(event.target.files ?? []))}
                />
              </Button>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                {localFiles.length ? `已选择 ${localFiles.length} 个文件：${localFiles.map((file) => file.name).join("、")}` : "尚未选择文件"}
              </Typography>
            </Box>
            <Stack direction="row" justifyContent="flex-end" sx={{ mt: 2 }}>
              <Button variant="contained" disabled={!localFiles.length || directSubmitting} onClick={() => void handleLocalUpload()}>
                {directSubmitting ? "上传中…" : `上传并入库${localFiles.length ? `（${localFiles.length}）` : ""}`}
              </Button>
            </Stack>
          </CardContent>
        </Card>
      )}

      {importMode === "account" && <><Card>
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
                  <MenuItem value={10}>10 条</MenuItem>
                  <MenuItem value={20}>20 条</MenuItem>
                  <MenuItem value={30}>30 条</MenuItem>
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
              <ListPagination page={page} pageSize={pageSize} total={page * pageSize} totalPages={totalPages} totalKnown={false}
                pageSizeOptions={[10, 20, 30]} onPageChange={(value) => void load(value, pageCursors[value - 1] ?? null)}
                onPageSizeChange={(value) => setPageSize(value)} />
            </>
          )}
        </CardContent>
      </Card></>}
    </>
  );
}
