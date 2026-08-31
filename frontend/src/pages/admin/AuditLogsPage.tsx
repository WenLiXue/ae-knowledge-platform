import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  Drawer,
  IconButton,
  LinearProgress,
  MenuItem,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import DownloadIcon from "@mui/icons-material/Download";
import RefreshIcon from "@mui/icons-material/Refresh";
import SearchIcon from "@mui/icons-material/Search";
import {
  createAuditExport,
  downloadAuditExport,
  getAuditExport,
  getAuditLogDetail,
  getAuditSummary,
  listAuditLogs,
} from "../../api/audit";
import { getErrorMessage } from "../../api/client";
import { EmptyState } from "../../components/EmptyState";
import { LoadingState } from "../../components/LoadingState";
import { ListPagination } from "../../components/ListPagination";
import { PageHeader } from "../../components/PageHeader";
import type {
  AuditExport,
  AuditLogDetail,
  AuditLogListItem,
  AuditLogSummary,
  AuditOutcome,
  AuditQueryParams,
} from "../../types/audit";
import {
  AUDIT_EXPORT_META,
  AUDIT_ACTION_LABEL,
  AUDIT_MODULE_LABEL,
  AUDIT_OUTCOME_META,
  AUDIT_TARGET_LABEL,
  statusLabel,
} from "../../types/statusMeta";

const MODULES = ["AUTH", "CONFIG", "AUDIT", "KNOWLEDGE", "TASKING"];

/** datetime-local 输入值 → 后端 ISO（无时区，后端按 UTC 处理）。 */
function toIso(local: string): string {
  return local ? `${local}:00` : "";
}

function toLocal(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function defaultRange(): { start: string; end: string } {
  const now = new Date();
  const ago = new Date(now.getTime() - 24 * 3600 * 1000);
  return { start: toLocal(ago.toISOString()), end: toLocal(now.toISOString()) };
}

function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function OutcomeChip({ outcome }: { outcome: string }) {
  const meta = statusLabel(AUDIT_OUTCOME_META, outcome);
  return <Chip size="small" label={meta.label} sx={{ bgcolor: meta.bg, color: meta.fg, fontWeight: 600 }} />;
}

type OutcomeTab = "all" | AuditOutcome;

/** 审计日志页：筛选、摘要、列表、详情抽屉与导出。 */
export function AuditLogsPage() {
  // 列表与筛选
  const [items, setItems] = useState<AuditLogListItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(20);
  // 游标接口没有页码，保存每一页的起始游标以支持上一页。
  const [pageCursors, setPageCursors] = useState<(string | null)[]>([null]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [summary, setSummary] = useState<AuditLogSummary | null>(null);

  // 表单草稿（未应用）
  const initial = defaultRange();
  const [keyword, setKeyword] = useState("");
  const [module, setModule] = useState("");
  const [action, setAction] = useState("");
  const [outcome, setOutcome] = useState<"" | AuditOutcome>("");
  const [startAt, setStartAt] = useState(initial.start);
  const [endAt, setEndAt] = useState(initial.end);
  // 结果 Tabs 由 outcome 派生，避免双控件状态冲突
  const tab: OutcomeTab = outcome === "" ? "all" : outcome;

  // 已应用的筛选
  const [applied, setApplied] = useState<AuditQueryParams>({
    start_at: toIso(initial.start),
    end_at: toIso(initial.end),
  });

  const paramsFrom = useCallback(
    (outcomeFilter: "" | AuditOutcome): AuditQueryParams => ({
      start_at: toIso(startAt),
      end_at: toIso(endAt),
      module: module || undefined,
      action: action.trim() || undefined,
      outcome: outcomeFilter || undefined,
      keyword: keyword.trim() || undefined,
    }),
    [startAt, endAt, module, action, keyword],
  );

  const loadSummary = useCallback(
    async (startIso: string, endIso: string) => {
      try {
        const data = await getAuditSummary(startIso, endIso);
        setSummary(data);
      } catch {
        // 摘要失败不阻塞列表展示
      }
    },
    [],
  );

  const loadFirstPage = useCallback(
    async (params: AuditQueryParams, summaryParams?: AuditQueryParams, size = pageSize) => {
      setLoading(true);
      setError(null);
      try {
        const data = await listAuditLogs({ ...params, limit: size });
        setItems(data.items);
        setNextCursor(data.next_cursor ?? null);
        setHasMore(data.has_more ?? false);
        setPage(0);
        setPageCursors([null]);
        if (summaryParams) {
          void loadSummary(summaryParams.start_at ?? "", summaryParams.end_at ?? "");
        }
      } catch (err) {
        setError(err);
      } finally {
        setLoading(false);
      }
    },
    [loadSummary, pageSize],
  );

  const applyFilters = useCallback(() => {
    const params = paramsFrom(outcome);
    setApplied(params);
    void loadFirstPage(params, params);
  }, [paramsFrom, outcome, loadFirstPage]);

  // 初始加载
  useEffect(() => {
    void loadFirstPage(applied, applied);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const changePage = async (nextPage: number) => {
    if (loading || nextPage < 0 || (nextPage > page && !hasMore)) return;
    const cursor = pageCursors[nextPage] ?? null;
    setLoading(true);
    try {
      const data = await listAuditLogs({ ...applied, cursor: cursor ?? undefined, limit: pageSize });
      setItems(data.items);
      setNextCursor(data.next_cursor ?? null);
      setHasMore(data.has_more ?? false);
      setPage(nextPage);
      if (nextPage === page + 1 && data.next_cursor) {
        setPageCursors((prev) => [...prev, data.next_cursor ?? null]);
      }
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  const totalPages = Math.max(1, Math.ceil((summary?.total ?? 0) / pageSize));

  const changePageSize = (size: number) => {
    setPageSize(size);
    void loadFirstPage(applied, applied, size);
  };

  const onTabChange = (_: unknown, value: OutcomeTab) => {
    const nextOutcome: "" | AuditOutcome = value === "all" ? "" : value;
    setOutcome(nextOutcome);
    const params = paramsFrom(nextOutcome);
    setApplied(params);
    void loadFirstPage(params, params);
  };

  const clearFilters = () => {
    const range = defaultRange();
    setKeyword("");
    setModule("");
    setAction("");
    setOutcome("");
    setStartAt(range.start);
    setEndAt(range.end);
    const params: AuditQueryParams = {
      start_at: toIso(range.start),
      end_at: toIso(range.end),
    };
    setApplied(params);
    void loadFirstPage(params, params);
  };

  // ---- 详情抽屉 ----
  const [detail, setDetail] = useState<AuditLogDetail | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  const openDetail = async (row: AuditLogListItem) => {
    setDetailOpen(true);
    setDetailLoading(true);
    setDetail(null);
    try {
      setDetail(await getAuditLogDetail(row.id));
    } catch (err) {
      setDetail((prev) =>
        prev ?? {
          ...row,
          changes: [],
          metadata: {},
          actor_user_id: null,
          actor_key: null,
          trace_id: null,
          causation_id: null,
          source_type: "API",
          user_agent: null,
          prev_hash: null,
          record_hash: "",
        },
      );
      setError(err);
    } finally {
      setDetailLoading(false);
    }
  };

  const copyId = async (id: string) => {
    try {
      await navigator.clipboard.writeText(id);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      // 剪贴板不可用忽略
    }
  };

  // ---- 导出 ----
  const [exportOpen, setExportOpen] = useState(false);
  const [exportTask, setExportTask] = useState<AuditExport | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportNotice, setExportNotice] = useState<string | null>(null);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stopPolling = () => {
    if (pollTimer.current) {
      clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
  };
  useEffect(() => stopPolling, []);

  const pollExport = useCallback((id: string) => {
    pollTimer.current = setTimeout(async () => {
      try {
        const row = await getAuditExport(id);
        setExportTask(row);
        if (row.status === "PENDING" || row.status === "RUNNING") {
          pollExport(id);
        }
      } catch {
        stopPolling();
      }
    }, 2500);
  }, []);

  const startExport = async () => {
    setExportError(null);
    setExportNotice(null);
    try {
      const row = await createAuditExport(applied);
      setExportTask(row);
      pollExport(row.id);
    } catch (err) {
      setExportError(getErrorMessage(err, "创建导出任务失败。"));
    }
  };

  const closeExport = () => {
    stopPolling();
    setExportOpen(false);
    setExportTask(null);
    setExportNotice(null);
    setExportError(null);
  };

  const doDownload = async (id: string) => {
    setExportError(null);
    try {
      await downloadAuditExport(id);
      setExportNotice("文件已开始下载。");
    } catch (err) {
      setExportError(getErrorMessage(err, "下载失败，请稍后重试。"));
    }
  };

  const outcomeCount = (o: AuditOutcome) =>
    summary?.by_outcome.find((item) => item.outcome === o)?.count ?? 0;

  const exportMeta = exportTask ? statusLabel(AUDIT_EXPORT_META, exportTask.status) : null;

  return (
    <>
      <PageHeader
        title="审计日志"
        description="追溯关键业务操作及执行结果；日志仅追加，不允许修改或删除。"
        actions={
          <>
            <Button
              variant="outlined"
              startIcon={<RefreshIcon />}
              onClick={() => void loadFirstPage(applied, applied)}
              disabled={loading}
            >
              刷新
            </Button>
            <Button
              variant="contained"
              startIcon={<DownloadIcon />}
              onClick={() => {
                setExportOpen(true);
                setExportTask(null);
              }}
            >
              导出当前结果
            </Button>
          </>
        }
      />
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {getErrorMessage(error, "加载失败")}
        </Alert>
      )}

      {/* 结果概览：成功 / 失败 / 拒绝 */}
      <Card sx={{ mb: 2 }}>
        <Tabs value={tab} onChange={onTabChange} variant="scrollable" allowScrollButtonsMobile>
          <Tab value="all" label={`全部结果 ${summary?.total ?? "…"}`} />
          <Tab value="SUCCESS" label={`成功 ${outcomeCount("SUCCESS")}`} />
          <Tab value="FAILURE" label={`失败 ${outcomeCount("FAILURE")}`} />
          <Tab value="DENIED" label={`拒绝 ${outcomeCount("DENIED")}`} />
        </Tabs>
        {summary && summary.by_module.length > 0 && (
          <Stack
            direction="row"
            spacing={1}
            flexWrap="wrap"
            sx={{ px: 2, pb: 1.5, pt: 0.5 }}
          >
            {summary.by_module.map((m) => (
              <Chip
                key={m.module}
                size="small"
                variant="outlined"
                label={`${AUDIT_MODULE_LABEL[m.module] ?? "其他模块"} ${m.count}`}
              />
            ))}
          </Stack>
        )}
      </Card>

      {/* 筛选 */}
      <Card sx={{ mb: 2 }}>
        <CardContent sx={{ p: 2 }}>
          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: {
                xs: "minmax(0, 1fr)",
                sm: "repeat(2, minmax(0, 1fr))",
                md: "repeat(6, minmax(0, 1fr))",
                xl: "minmax(220px, 2fr) repeat(3, minmax(130px, 1fr)) repeat(2, minmax(200px, 1.4fr)) auto",
              },
              gap: 2,
              alignItems: "center",
            }}
          >
            <TextField
              size="small"
              label="日志内容"
              placeholder="搜索操作者或操作对象"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") applyFilters();
              }}
              InputProps={{ startAdornment: <SearchIcon fontSize="small" sx={{ mr: 1, color: "text.secondary" }} /> }}
              sx={{ gridColumn: { xs: "auto", sm: "span 2", md: "span 3", xl: "auto" } }}
            />
            <TextField
              size="small"
              select
              label="业务模块"
              value={module}
              onChange={(e) => setModule(e.target.value)}
              sx={{ gridColumn: { xs: "auto", md: "span 1", xl: "auto" } }}
            >
              <MenuItem value="">全部模块</MenuItem>
              {MODULES.map((m) => (
                <MenuItem key={m} value={m}>
                  {AUDIT_MODULE_LABEL[m] ?? "其他模块"}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              size="small"
              label="操作动作"
              placeholder="如 auth.login"
              value={action}
              onChange={(e) => setAction(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") applyFilters();
              }}
              sx={{ gridColumn: { xs: "auto", md: "span 1", xl: "auto" } }}
            />
            <TextField
              size="small"
              select
              label="执行结果"
              value={outcome}
              onChange={(e) => setOutcome(e.target.value as AuditOutcome | "")}
              sx={{ gridColumn: { xs: "auto", md: "span 1", xl: "auto" } }}
            >
              <MenuItem value="">全部结果</MenuItem>
              <MenuItem value="SUCCESS">成功</MenuItem>
              <MenuItem value="FAILURE">失败</MenuItem>
              <MenuItem value="DENIED">拒绝</MenuItem>
            </TextField>
            <TextField
              size="small"
              type="datetime-local"
              label="开始时间"
              value={startAt}
              onChange={(e) => setStartAt(e.target.value)}
              InputLabelProps={{ shrink: true }}
              sx={{ gridColumn: { xs: "auto", md: "span 2", xl: "auto" } }}
            />
            <TextField
              size="small"
              type="datetime-local"
              label="结束时间"
              value={endAt}
              onChange={(e) => setEndAt(e.target.value)}
              InputLabelProps={{ shrink: true }}
              sx={{ gridColumn: { xs: "auto", md: "span 2", xl: "auto" } }}
            />
            <Stack
              direction="row"
              spacing={1}
              sx={{
                gridColumn: { xs: "auto", sm: "span 2", md: "span 2", xl: "auto" },
                justifyContent: { xs: "stretch", sm: "flex-end" },
                "& > .MuiButton-root": { flex: { xs: 1, sm: "0 0 auto" } },
              }}
            >
              <Button variant="contained" onClick={() => applyFilters()} disabled={loading}>
                查询
              </Button>
              <Button variant="outlined" onClick={clearFilters} disabled={loading}>
                清除
              </Button>
            </Stack>
          </Box>
        </CardContent>
      </Card>

      {/* 列表 */}
      <Card>
        <CardContent sx={{ p: 0 }}>
          {loading && items.length === 0 ? (
            <Box sx={{ p: 6 }}>
              <LoadingState label="正在加载审计日志…" />
            </Box>
          ) : items.length === 0 ? (
            <Box sx={{ p: 6 }}>
              <EmptyState title="暂无审计日志" description="没有符合当前条件的操作审计记录。" />
            </Box>
          ) : (
            <>
              <TableContainer>
                <Table size="small" sx={{ minWidth: 980 }}>
                  <TableHead>
                    <TableRow>
                      <TableCell sx={{ fontWeight: 700 }}>时间</TableCell>
                      <TableCell sx={{ fontWeight: 700 }}>操作者</TableCell>
                      <TableCell sx={{ fontWeight: 700 }}>业务模块</TableCell>
                      <TableCell sx={{ fontWeight: 700 }}>操作</TableCell>
                      <TableCell sx={{ fontWeight: 700 }}>操作对象</TableCell>
                      <TableCell sx={{ fontWeight: 700 }}>结果</TableCell>
                      <TableCell sx={{ fontWeight: 700 }}>来源 IP</TableCell>
                      <TableCell sx={{ fontWeight: 700 }}>操作</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {items.map((row) => (
                      <TableRow
                        key={row.id}
                        hover
                        onClick={() => void openDetail(row)}
                        sx={{ cursor: "pointer" }}
                      >
                        <TableCell sx={{ py: 1.5 }}>
                          <Typography variant="body2" fontWeight={600}>
                            {formatTime(row.occurred_at)}
                          </Typography>
                        </TableCell>
                        <TableCell sx={{ py: 1.5 }}>
                          <Typography variant="body2">{row.actor_name}</Typography>
                          {row.actor_account && (
                            <Typography variant="caption" color="text.secondary">
                              {row.actor_account}
                            </Typography>
                          )}
                        </TableCell>
                        <TableCell sx={{ py: 1.5 }}>
                          <Typography variant="body2">{AUDIT_MODULE_LABEL[row.module] ?? "其他模块"}</Typography>
                        </TableCell>
                        <TableCell sx={{ py: 1.5 }}>
                          <Typography variant="body2" sx={{ fontFamily: "monospace", fontSize: 12.5 }}>
                            {AUDIT_ACTION_LABEL[row.action] ?? "其他操作"}
                          </Typography>
                        </TableCell>
                        <TableCell sx={{ py: 1.5 }}>
                          <Typography variant="body2" color={row.target_name ? "text.primary" : "text.secondary"}>
                            {row.target_name ?? (row.target_type ? `${AUDIT_TARGET_LABEL[row.target_type] ?? "其他对象"}` : "—")}
                          </Typography>
                        </TableCell>
                        <TableCell sx={{ py: 1.5 }}>
                          <OutcomeChip outcome={row.outcome} />
                        </TableCell>
                        <TableCell sx={{ py: 1.5 }}>
                          <Typography variant="body2" sx={{ fontFamily: "monospace", fontSize: 12.5 }}>
                            {row.source_ip ?? "—"}
                          </Typography>
                        </TableCell>
                        <TableCell sx={{ py: 1.5 }}>
                          <Button size="small" onClick={(e) => { e.stopPropagation(); void openDetail(row); }}>
                            查看
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
              <Stack
                spacing={1.5}
                alignItems="center"
                sx={{ px: 2, py: 1.5, borderTop: 1, borderColor: "divider" }}
              >
                <ListPagination
                  page={page + 1}
                  pageSize={pageSize}
                  total={summary?.total ?? items.length}
                  totalPages={totalPages}
                  loading={loading}
                  pageSizeOptions={[10, 20, 30]}
                  onPageChange={(value) => void changePage(value - 1)}
                  onPageSizeChange={changePageSize}
                />
              </Stack>
            </>
          )}
        </CardContent>
      </Card>

      {/* 详情抽屉 */}
      <Drawer anchor="right" open={detailOpen} onClose={() => setDetailOpen(false)}>
        <Box sx={{ width: { xs: "100vw", sm: 460 }, display: "flex", flexDirection: "column", height: "100%" }}>
          <Stack
            direction="row"
            alignItems="center"
            justifyContent="space-between"
            sx={{ px: 2.5, py: 2, borderBottom: 1, borderColor: "divider" }}
          >
            <Box>
              <Typography variant="overline" color="text.secondary">
                审计详情
              </Typography>
              <Typography variant="h6" sx={{ fontFamily: "monospace", fontSize: 15 }}>
                {detail?.id.slice(0, 8) ?? "…"}
              </Typography>
            </Box>
            <IconButton onClick={() => setDetailOpen(false)} aria-label="关闭">
              <CloseIcon />
            </IconButton>
          </Stack>

          <Box sx={{ flexGrow: 1, overflowY: "auto", px: 2.5, py: 2 }}>
            {detailLoading ? (
              <LoadingState label="正在加载详情…" />
            ) : detail ? (
              <Stack spacing={2.5}>
                <Box sx={{ bgcolor: "action.hover", borderRadius: 2, p: 2 }}>
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                    <OutcomeChip outcome={detail.outcome} />
                    {detail.error_code && (
                      <Chip size="small" label={detail.error_code} sx={{ fontFamily: "monospace" }} />
                    )}
                  </Stack>
                  <Typography variant="body2" sx={{ fontFamily: "monospace" }}>
                    {AUDIT_ACTION_LABEL[detail.action] ?? "其他操作"}
                  </Typography>
                  <Typography variant="body1" sx={{ mt: 1 }}>
                    {detail.summary}
                  </Typography>
                </Box>

                <Box>
                  <Typography variant="overline" color="text.secondary">
                    基本信息
                  </Typography>
                  <Stack spacing={0.75} sx={{ mt: 0.5 }}>
                    {[
                      ["操作者", detail.actor_name],
                      ["账号", detail.actor_account ?? "—"],
                      ["操作时间", formatTime(detail.occurred_at)],
                      ["来源 IP", detail.source_ip ?? "—"],
                      ["业务模块", AUDIT_MODULE_LABEL[detail.module] ?? "其他模块"],
                      ["请求编号", detail.request_id],
                      ["日志编号", detail.id],
                    ].map(([label, value]) => (
                      <Stack key={label} direction="row" spacing={2} sx={{ justifyContent: "space-between" }}>
                        <Typography variant="body2" color="text.secondary" sx={{ flexShrink: 0 }}>
                          {label}
                        </Typography>
                        <Typography
                          variant="body2"
                          sx={{ textAlign: "right", wordBreak: "break-all", fontFamily: label === "日志编号" ? "monospace" : undefined }}
                        >
                          {value}
                        </Typography>
                      </Stack>
                    ))}
                  </Stack>
                </Box>

                <Divider />

                <Box>
                  <Typography variant="overline" color="text.secondary">
                    变更内容
                  </Typography>
                  <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
                    仅展示允许记录的非敏感字段，敏感值一律脱敏。
                  </Typography>
                  {detail.changes.length === 0 ? (
                    <Typography variant="body2" color="text.secondary">
                      本次操作没有记录字段级变更。
                    </Typography>
                  ) : (
                    <Stack spacing={1}>
                      {detail.changes.map((change, index) => (
                        <Box
                          key={`${change.field}-${index}`}
                          sx={{ bgcolor: "action.hover", borderRadius: 1.5, px: 1.5, py: 1 }}
                        >
                          <Typography variant="body2" fontWeight={600} sx={{ fontFamily: "monospace", fontSize: 12.5 }}>
                            {change.field}
                          </Typography>
                          <Typography variant="body2" color="text.secondary">
                            {formatValue(change.before)} → {formatValue(change.after)}
                          </Typography>
                        </Box>
                      ))}
                    </Stack>
                  )}
                </Box>

                {Object.keys(detail.metadata ?? {}).length > 0 && (
                  <>
                    <Divider />
                    <Box>
                      <Typography variant="overline" color="text.secondary">
                        补充信息
                      </Typography>
                      <pre
                        style={{
                          margin: 0,
                          fontSize: 12,
                          whiteSpace: "pre-wrap",
                          wordBreak: "break-all",
                          color: "text.secondary",
                        }}
                      >
                        {JSON.stringify(detail.metadata, null, 2)}
                      </pre>
                    </Box>
                  </>
                )}

                <Divider />
                <Box>
                  <Typography variant="overline" color="text.secondary">
                    完整性校验
                  </Typography>
                  <Typography variant="caption" color="text.secondary" display="block">
                    记录哈希（HMAC-SHA256）与前序哈希构成防篡改链；两端省略展示。
                  </Typography>
                  <Typography variant="caption" sx={{ display: "block", fontFamily: "monospace", mt: 0.5 }}>
                    prev: {detail.prev_hash ?? "（首条记录）"}
                  </Typography>
                  <Typography variant="caption" sx={{ display: "block", fontFamily: "monospace" }}>
                    hash: {detail.record_hash}
                  </Typography>
                </Box>
              </Stack>
            ) : null}
          </Box>

          <Stack
            direction="row"
            spacing={1}
            justifyContent="flex-end"
            sx={{ px: 2.5, py: 2, borderTop: 1, borderColor: "divider" }}
          >
            <Button variant="outlined" onClick={() => void copyId(detail?.id ?? "")} startIcon={<ContentCopyIcon />}>
              {copied ? "已复制" : "复制日志编号"}
            </Button>
            <Button variant="contained" onClick={() => setDetailOpen(false)}>
              关闭
            </Button>
          </Stack>
        </Box>
      </Drawer>

      {/* 导出对话框 */}
      <Dialog open={exportOpen} onClose={closeExport} maxWidth="sm" fullWidth>
        <DialogTitle>导出审计日志</DialogTitle>
        <DialogContent>
          <Stack spacing={2}>
            <Typography variant="body2" color="text.secondary">
              将按当前筛选条件导出 CSV 文件（UTF-8 BOM，含公式注入防护）。文件保留 24 小时，最多
              10 万条。
            </Typography>
            {!exportTask && (
              <Button variant="contained" startIcon={<DownloadIcon />} onClick={() => void startExport()}>
                开始导出
              </Button>
            )}
            {exportError && <Alert severity="error">{exportError}</Alert>}
            {exportNotice && <Alert severity="success">{exportNotice}</Alert>}
            {exportTask && (
              <Box>
                <Stack direction="row" spacing={2} alignItems="center" justifyContent="space-between">
                  <Box>
                    <Typography variant="body2" fontWeight={600}>
                      导出任务
                    </Typography>
                    <Typography variant="caption" color="text.secondary" sx={{ fontFamily: "monospace" }}>
                      {exportTask.id.slice(0, 8)}…
                    </Typography>
                  </Box>
                  {exportMeta && (
                    <Chip size="small" label={exportMeta.label} sx={{ bgcolor: exportMeta.bg, color: exportMeta.fg, fontWeight: 600 }} />
                  )}
                </Stack>
                {(exportTask.status === "PENDING" || exportTask.status === "RUNNING") && (
                  <Box sx={{ mt: 1.5 }}>
                    <LinearProgress />
                    <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5 }}>
                      正在生成，请稍候…
                    </Typography>
                  </Box>
                )}
                {exportTask.status === "READY" && (
                  <Alert severity="success" sx={{ mt: 1.5 }}>
                    已生成 {exportTask.row_count} 条记录。
                  </Alert>
                )}
                {exportTask.status === "FAILED" && (
                  <Alert severity="error" sx={{ mt: 1.5 }}>
                    导出失败：{exportTask.error_code ?? "未知错误"}
                  </Alert>
                )}
                {exportTask.status === "EXPIRED" && (
                  <Alert severity="warning" sx={{ mt: 1.5 }}>
                    导出文件已过期，请重新导出。
                  </Alert>
                )}
              </Box>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          {exportTask?.status === "READY" && (
            <Button variant="contained" startIcon={<DownloadIcon />} onClick={() => void doDownload(exportTask.id)}>
              下载文件
            </Button>
          )}
          <Button onClick={closeExport}>关闭</Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
