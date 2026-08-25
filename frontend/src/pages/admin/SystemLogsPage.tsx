import { useCallback, useEffect, useState } from "react";
import {
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Dialog,
  DialogContent,
  DialogTitle,
  IconButton,
  MenuItem,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import { adminListSystemLogs, type SystemLogQuery } from "../../api/logs";
import { ErrorAlert } from "../../components/ErrorAlert";
import { EmptyState } from "../../components/EmptyState";
import { LoadingState } from "../../components/LoadingState";
import { PageHeader } from "../../components/PageHeader";
import type { SystemLogItem } from "../../types/logs";

const PAGE_SIZE = 20;

const LEVEL_OPTIONS = ["", "ERROR", "WARNING", "INFO", "DEBUG"];
const SERVICE_OPTIONS = ["", "api", "worker"];

function levelColor(level: string): "error" | "warning" | "info" | "default" {
  if (level === "ERROR") return "error";
  if (level === "WARNING") return "warning";
  if (level === "INFO") return "info";
  return "default";
}

function formatTime(iso: string | null): string {
  if (!iso) return "-";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

function Mono({ text }: { text: string }) {
  return (
    <Typography variant="body2" sx={{ fontFamily: "monospace", fontSize: 12 }}>
      {text}
    </Typography>
  );
}

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography
        variant="body2"
        sx={
          mono
            ? { fontFamily: "monospace", fontSize: 12, whiteSpace: "pre-wrap", wordBreak: "break-all" }
            : { whiteSpace: "pre-wrap", wordBreak: "break-all" }
        }
      >
        {value}
      </Typography>
    </Box>
  );
}

/** 系统日志页：查看 ERROR+ 落库的运行日志，支持关键词/关联 ID/级别/服务筛选与分页。 */
export function SystemLogsPage() {
  const [keyword, setKeyword] = useState("");
  const [requestId, setRequestId] = useState("");
  const [level, setLevel] = useState("");
  const [service, setService] = useState("");

  const [rows, setRows] = useState<SystemLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [detail, setDetail] = useState<SystemLogItem | null>(null);

  const buildQuery = useCallback(
    (pageNo: number): SystemLogQuery => ({
      keyword: keyword.trim() || undefined,
      request_id: requestId.trim() || undefined,
      level: level || undefined,
      service: service || undefined,
      limit: PAGE_SIZE,
      offset: pageNo * PAGE_SIZE,
    }),
    [keyword, requestId, level, service],
  );

  const load = useCallback(
    async (query: SystemLogQuery) => {
      setLoading(true);
      setError(null);
      try {
        const data = await adminListSystemLogs(query);
        setRows(data.items);
        setTotal(data.total);
      } catch (err) {
        setError(err);
        setRows([]);
        setTotal(0);
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    void load(buildQuery(0));
  }, [load, buildQuery]);

  const search = () => {
    setPage(0);
    void load(buildQuery(0));
  };

  const reset = () => {
    setKeyword("");
    setRequestId("");
    setLevel("");
    setService("");
    setPage(0);
    void load({ limit: PAGE_SIZE, offset: 0 });
  };

  const changePage = (_event: unknown, next: number) => {
    setPage(next);
    void load(buildQuery(next));
  };

  return (
    <>
      <PageHeader
        title="系统日志"
        description="查看持久化的运行日志（ERROR 及以上），支持按级别、服务、关联 ID 与关键词筛选。"
      />
      {error && <ErrorAlert error={error} onRetry={search} title="加载失败" />}
      <Card sx={{ mb: 2 }}>
        <CardContent sx={{ p: { xs: 2, sm: 3 } }}>
          <Stack
            direction={{ xs: "column", sm: "row" }}
            spacing={2}
            flexWrap="wrap"
            useFlexGap
            alignItems="center"
          >
            <TextField
              size="small"
              label="关键词"
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && search()}
              sx={{ minWidth: 160 }}
            />
            <TextField
              size="small"
              label="Request ID"
              value={requestId}
              onChange={(event) => setRequestId(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && search()}
              sx={{ minWidth: 200 }}
            />
            <TextField
              select
              size="small"
              label="级别"
              value={level}
              onChange={(event) => setLevel(event.target.value)}
              sx={{ minWidth: 120 }}
            >
              {LEVEL_OPTIONS.map((option) => (
                <MenuItem key={option || "all"} value={option}>
                  {option || "全部"}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              size="small"
              label="服务"
              value={service}
              onChange={(event) => setService(event.target.value)}
              sx={{ minWidth: 120 }}
            >
              {SERVICE_OPTIONS.map((option) => (
                <MenuItem key={option || "all"} value={option}>
                  {option || "全部"}
                </MenuItem>
              ))}
            </TextField>
            <Stack direction="row" spacing={1}>
              <Button variant="contained" onClick={search}>
                查询
              </Button>
              <Button variant="outlined" onClick={reset}>
                重置
              </Button>
            </Stack>
          </Stack>
        </CardContent>
      </Card>

      <Card>
        {loading ? (
          <LoadingState label="正在加载日志…" />
        ) : rows.length === 0 ? (
          <EmptyState
            title="没有日志记录"
            description="调整筛选条件后再试，或等待新的错误日志写入。"
          />
        ) : (
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>时间</TableCell>
                  <TableCell>级别</TableCell>
                  <TableCell>服务</TableCell>
                  <TableCell>消息</TableCell>
                  <TableCell>错误码</TableCell>
                  <TableCell>Request ID</TableCell>
                  <TableCell>Task ID</TableCell>
                  <TableCell>操作</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.id} hover>
                    <TableCell sx={{ whiteSpace: "nowrap" }}>{formatTime(row.created_at)}</TableCell>
                    <TableCell>
                      <Chip size="small" color={levelColor(row.level)} label={row.level} />
                    </TableCell>
                    <TableCell>{row.service}</TableCell>
                    <TableCell sx={{ maxWidth: 320 }}>
                      <Typography variant="body2" noWrap title={row.message}>
                        {row.message}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      {row.error_code ? <Mono text={row.error_code} /> : "-"}
                    </TableCell>
                    <TableCell>{row.request_id ? <Mono text={row.request_id} /> : "-"}</TableCell>
                    <TableCell>{row.task_id ? <Mono text={row.task_id} /> : "-"}</TableCell>
                    <TableCell>
                      <Button size="small" onClick={() => setDetail(row)}>
                        详情
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
        {!loading && rows.length > 0 && (
          <TablePagination
            component="div"
            count={total}
            page={page}
            rowsPerPage={PAGE_SIZE}
            rowsPerPageOptions={[PAGE_SIZE]}
            onPageChange={changePage}
          />
        )}
      </Card>

      <Dialog open={detail !== null} onClose={() => setDetail(null)} maxWidth="md" fullWidth>
        <DialogTitle
          sx={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}
        >
          <Box component="span" sx={{ fontSize: 16, fontWeight: 700 }}>
            日志详情
          </Box>
          <IconButton onClick={() => setDetail(null)} size="small" aria-label="关闭">
            <CloseIcon fontSize="small" />
          </IconButton>
        </DialogTitle>
        <DialogContent dividers>
          {detail && (
            <Stack spacing={1.5}>
              <Field label="时间" value={formatTime(detail.created_at)} />
              <Field label="级别 / 服务" value={`${detail.level} / ${detail.service}`} />
              <Field label="消息" value={detail.message} />
              <Field label="错误码" value={detail.error_code ?? "-"} mono />
              <Field label="Request ID" value={detail.request_id ?? "-"} mono />
              <Field label="Task ID" value={detail.task_id ?? "-"} mono />
              <Field label="Source ID" value={detail.source_id ?? "-"} mono />
              <Field label="Version ID" value={detail.version_id ?? "-"} mono />
              <Field label="用户" value={detail.user_id ?? "-"} mono />
              <Field label="IP" value={detail.ip ?? "-"} />
              {Object.keys(detail.detail).length > 0 && (
                <Field label="详情" value={JSON.stringify(detail.detail, null, 2)} mono />
              )}
              {detail.traceback && <Field label="堆栈" value={detail.traceback} mono />}
            </Stack>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
