import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import RefreshIcon from "@mui/icons-material/Refresh";
import { listKnowledgeSources } from "../api/knowledgeSources";
import { EmptyState } from "../components/EmptyState";
import { ErrorAlert } from "../components/ErrorAlert";
import { LoadingState } from "../components/LoadingState";
import { ListPagination } from "../components/ListPagination";
import { PageHeader } from "../components/PageHeader";
import { StatusChip } from "../components/StatusChip";
import { RESOURCE_TYPE_LABEL, SOURCE_STATUS_META } from "../types/statusMeta";
import type { ClassificationSummary, KnowledgeSource } from "../types/documents";

const SOURCE_STATUS_OPTIONS = Object.keys(SOURCE_STATUS_META);
const TYPE_OPTIONS = ["WIKI", "DOCX"];

function formatTime(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** 已入库文档页：来源列表、搜索、状态/类型筛选、查看详情、刷新。 */
export function DocumentsPage() {
  const navigate = useNavigate();

  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);

  const load = useCallback(async (nextPage = 1, nextSize = pageSize) => {
    setLoading(true);
    setError(null);
    try {
      const result = await listKnowledgeSources({ limit: nextSize, offset: (nextPage - 1) * nextSize });
      setSources(result.items);
      setTotal(result.total);
      setPage(nextPage);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [pageSize]);

  useEffect(() => {
    void load();
  }, [load]);

  const visibleSources = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return sources.filter((source) => {
      if (keyword && !source.display_name.toLowerCase().includes(keyword)) return false;
      if (statusFilter && source.status !== statusFilter) return false;
      if (typeFilter && source.resource_type !== typeFilter) return false;
      return true;
    });
  }, [sources, query, statusFilter, typeFilter]);

  return (
    <>
      <PageHeader
        title="已入库文档"
        description="查看已提交入库的知识来源及其处理状态，点击行可查看详情。"
      />

      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ mb: 3 }}>
        <TextField
          size="small"
          label="搜索文档"
          placeholder="按标题筛选"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          fullWidth
        />
        <FormControl size="small" sx={{ minWidth: { sm: 160 } }}>
          <InputLabel>状态</InputLabel>
          <Select
            label="状态"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
          >
            <MenuItem value="">全部状态</MenuItem>
            {SOURCE_STATUS_OPTIONS.map((status) => (
              <MenuItem key={status} value={status}>
                {SOURCE_STATUS_META[status].label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: { sm: 160 } }}>
          <InputLabel>来源类型</InputLabel>
          <Select label="来源类型" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
            <MenuItem value="">全部类型</MenuItem>
            {TYPE_OPTIONS.map((type) => (
              <MenuItem key={type} value={type}>
                {RESOURCE_TYPE_LABEL[type] ?? type}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <Button variant="outlined" startIcon={<RefreshIcon />} onClick={() => void load()} disabled={loading}>
          刷新
        </Button>
      </Stack>

      {error && <ErrorAlert error={error} onRetry={() => void load()} title="加载失败" />}

      <Card>
        <CardContent sx={{ p: { xs: 1, sm: 2 } }}>
          {loading ? (
            <Box sx={{ py: 3 }}>
              <LoadingState label="正在加载已入库文档…" />
            </Box>
          ) : visibleSources.length === 0 ? (
            <Box sx={{ py: 3 }}>
              <EmptyState
                title="暂无已入库文档"
                description="先在「文档导入」页提交飞书文档，处理完成后会出现在这里。"
              />
            </Box>
          ) : (
            <Table size="small" sx={{ minWidth: 760 }}>
              <TableHead>
                <TableRow>
                  <TableCell>文档</TableCell>
                  <TableCell>来源类型</TableCell>
                  <TableCell>分类</TableCell>
                  <TableCell>来源状态</TableCell>
                  <TableCell>版本状态</TableCell>
                  <TableCell>任务状态</TableCell>
                  <TableCell>提交时间</TableCell>
                  <TableCell>操作</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {visibleSources.map((source) => {
                  // 列表分类为轻量 Summary 形状（产品/类型），详情才是 Detail 形状
                  const cls: ClassificationSummary | null =
                    source.classification && "product_code" in source.classification
                      ? source.classification
                      : null;
                  const productName = cls?.product_name ?? cls?.product_code ?? null;
                  const typeName = cls?.document_type_name ?? cls?.document_type_code ?? null;
                  return (
                  <TableRow
                    key={source.source_id}
                    hover
                    sx={{ cursor: "pointer" }}
                    onClick={() => navigate(`/documents/${source.source_id}`)}
                  >
                    <TableCell>
                      <Typography variant="body2" fontWeight={600} noWrap sx={{ maxWidth: 260 }}>
                        {source.display_name}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      {source.resource_type ? (
                        <Chip
                          size="small"
                          label={RESOURCE_TYPE_LABEL[source.resource_type] ?? source.resource_type}
                          variant="outlined"
                        />
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell>
                      {productName || typeName ? (
                        <Typography variant="body2">
                          {productName && <Box component="span" fontWeight={600}>{productName}</Box>}
                          {productName && typeName && (
                            <Box component="span" sx={{ color: "text.disabled", mx: 0.5 }}>·</Box>
                          )}
                          {typeName && <Box component="span" sx={{ color: "text.secondary" }}>{typeName}</Box>}
                        </Typography>
                      ) : source.status === "PENDING_CONFIRMATION" ? (
                        <Chip size="small" label="待分类确认" color="warning" variant="outlined" />
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell>
                      <StatusChip value={source.status} kind="source" />
                    </TableCell>
                    <TableCell>
                      <StatusChip value={source.version_status} kind="version" />
                    </TableCell>
                    <TableCell>
                      <StatusChip value={source.task_status} kind="task" />
                    </TableCell>
                    <TableCell>{formatTime(source.created_at)}</TableCell>
                    <TableCell>
                      <Button size="small" onClick={(event) => event.stopPropagation()}>
                        查看详情
                      </Button>
                    </TableCell>
                  </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      <ListPagination page={page} pageSize={pageSize} total={total} loading={loading}
        onPageChange={(value) => void load(value)}
        onPageSizeChange={(value) => { setPageSize(value); void load(1, value); }} />
    </>
  );
}
