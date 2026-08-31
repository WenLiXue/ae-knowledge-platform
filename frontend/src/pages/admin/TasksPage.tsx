/**
 * 处理任务页（DD-03，需要登录）。
 *
 * 查看文档入库流水线任务（FETCH→…→FINALIZE 及 CLEANUP / GENERATE_ANSWER）的执行情况：
 * 类型、状态、来源、版本处理阶段、尝试次数与最近错误；支持按类型/状态/来源筛选与分页。
 */
import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  MenuItem,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import RefreshIcon from "@mui/icons-material/Refresh";
import SearchIcon from "@mui/icons-material/Search";
import { listAdminTasks, type AdminTask } from "../../api/admin";
import { getErrorMessage } from "../../api/client";
import { EmptyState } from "../../components/EmptyState";
import { LoadingState } from "../../components/LoadingState";
import { ListPagination } from "../../components/ListPagination";
import { PageHeader } from "../../components/PageHeader";
import { TASK_STATUS_META, TASK_TYPE_META, statusLabel } from "../../types/statusMeta";

const TASK_TYPES = ["FETCH", "PARSE", "CLASSIFY", "CHUNK", "EMBED", "INDEX", "FINALIZE", "CLEANUP", "GENERATE_ANSWER"];
const PAGE_SIZE = 50;

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function typeLabel(type: string): string {
  return TASK_TYPE_META[type] ?? type;
}

export function TasksPage() {
  const [items, setItems] = useState<AdminTask[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  // 筛选
  const [taskType, setTaskType] = useState("");
  const [status, setStatus] = useState("");
  const [keyword, setKeyword] = useState("");

  const load = useCallback(async (nextPage: number, filter?: { taskType: string; status: string; keyword: string }) => {
    setLoading(true);
    setError(null);
    const f = filter ?? { taskType, status, keyword };
    try {
      const data = await listAdminTasks({
        task_type: f.taskType || undefined,
        status: f.status || undefined,
        keyword: f.keyword.trim() || undefined,
        limit: PAGE_SIZE,
        offset: nextPage * PAGE_SIZE,
      });
      setItems(data.items);
      setTotal(data.total);
      setPage(nextPage);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [taskType, status, keyword]);

  useEffect(() => {
    void load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const applyFilters = () => void load(0, { taskType, status, keyword });

  const clearFilters = () => {
    setTaskType("");
    setStatus("");
    setKeyword("");
    void load(0, { taskType: "", status: "", keyword: "" });
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <>
      <PageHeader
        title="处理任务"
        description="文档入库流水线任务与执行进度；按类型、状态与来源关键字筛选。"
        actions={
          <Button variant="outlined" startIcon={<RefreshIcon />} onClick={() => void applyFilters()} disabled={loading}>
            刷新
          </Button>
        }
      />
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {getErrorMessage(error, "加载失败")}
        </Alert>
      )}

      {/* 筛选 */}
      <Card sx={{ mb: 2 }}>
        <CardContent sx={{ p: 2 }}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems="center">
            <TextField
              size="small"
              select
              label="任务类型"
              value={taskType}
              onChange={(e) => setTaskType(e.target.value)}
              sx={{ minWidth: 160 }}
            >
              <MenuItem value="">全部类型</MenuItem>
              {TASK_TYPES.map((t) => (
                <MenuItem key={t} value={t}>{typeLabel(t)}</MenuItem>
              ))}
            </TextField>
            <TextField
              size="small"
              select
              label="任务状态"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              sx={{ minWidth: 140 }}
            >
              <MenuItem value="">全部状态</MenuItem>
              {Object.entries(TASK_STATUS_META).map(([value, meta]) => (
                <MenuItem key={value} value={value}>{meta.label}</MenuItem>
              ))}
            </TextField>
            <TextField
              size="small"
              label="来源名称 / 幂等键"
              placeholder="搜索来源"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") applyFilters();
              }}
              sx={{ flexGrow: 1, minWidth: 200 }}
              InputProps={{ startAdornment: <SearchIcon fontSize="small" sx={{ mr: 1, color: "text.secondary" }} /> }}
            />
            <Stack direction="row" spacing={1} sx={{ flexShrink: 0 }}>
              <Button variant="contained" onClick={applyFilters} disabled={loading}>查询</Button>
              <Button variant="outlined" onClick={clearFilters} disabled={loading}>清除</Button>
            </Stack>
          </Stack>
        </CardContent>
      </Card>

      {/* 列表 */}
      <Card>
        <CardContent sx={{ p: 0 }}>
          {loading && items.length === 0 ? (
            <Box sx={{ p: 6 }}>
              <LoadingState label="正在加载任务列表…" />
            </Box>
          ) : items.length === 0 ? (
            <Box sx={{ p: 6 }}>
              <EmptyState title="暂无任务" description="没有符合当前条件的处理任务。" />
            </Box>
          ) : (
            <>
              <TableContainer>
                <Table size="small" sx={{ minWidth: 1000 }}>
                  <TableHead>
                    <TableRow>
                      <TableCell sx={{ fontWeight: 700 }}>任务 ID</TableCell>
                      <TableCell sx={{ fontWeight: 700 }}>类型</TableCell>
                      <TableCell sx={{ fontWeight: 700 }}>状态</TableCell>
                      <TableCell sx={{ fontWeight: 700 }}>来源 / 版本阶段</TableCell>
                      <TableCell sx={{ fontWeight: 700 }}>尝试</TableCell>
                      <TableCell sx={{ fontWeight: 700 }}>创建时间</TableCell>
                      <TableCell sx={{ fontWeight: 700 }}>最近错误</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {items.map((task) => {
                      const statusMeta = statusLabel(TASK_STATUS_META, task.status);
                      return (
                        <TableRow key={task.task_id} hover>
                          <TableCell sx={{ py: 1.5 }}>
                            <Typography variant="body2" sx={{ fontFamily: "monospace", fontSize: 12.5 }}>
                              {task.task_id.slice(0, 8)}…
                            </Typography>
                          </TableCell>
                          <TableCell sx={{ py: 1.5 }}>
                            <Typography variant="body2">{typeLabel(task.task_type)}</Typography>
                            {task.task_type === "GENERATE_ANSWER" && (
                              <Typography variant="caption" color="text.secondary">问答生成</Typography>
                            )}
                          </TableCell>
                          <TableCell sx={{ py: 1.5 }}>
                            <Chip size="small" label={statusMeta.label} sx={{ bgcolor: statusMeta.bg, color: statusMeta.fg, fontWeight: 600 }} />
                          </TableCell>
                          <TableCell sx={{ py: 1.5 }}>
                            <Typography variant="body2">{task.source_name ?? "—"}</Typography>
                            {task.stage && (
                              <Typography variant="caption" color="text.secondary">{task.stage}</Typography>
                            )}
                          </TableCell>
                          <TableCell sx={{ py: 1.5 }}>
                            <Typography variant="body2">
                              {task.attempt_count} / {task.max_attempts}
                            </Typography>
                          </TableCell>
                          <TableCell sx={{ py: 1.5 }}>
                            <Typography variant="body2" color="text.secondary">
                              {formatTime(task.created_at)}
                            </Typography>
                          </TableCell>
                          <TableCell sx={{ py: 1.5 }}>
                            {task.last_error_summary ? (
                              <Typography variant="body2" color="error" sx={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                {task.last_error_code ? `[${task.last_error_code}] ` : ""}{task.last_error_summary}
                              </Typography>
                            ) : (
                              <Typography variant="body2" color="text.secondary">—</Typography>
                            )}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </TableContainer>
              <Stack spacing={1.5} alignItems="center" sx={{ px: 2, py: 1.5, borderTop: 1, borderColor: "divider" }}>
                <ListPagination page={page + 1} pageSize={PAGE_SIZE} total={total} totalPages={totalPages}
                  loading={loading} pageSizeOptions={[10, 20, 30]} onPageChange={(value) => void load(value - 1)} />
              </Stack>
            </>
          )}
        </CardContent>
      </Card>
    </>
  );
}
