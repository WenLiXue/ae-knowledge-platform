import { FormControl, MenuItem, Pagination, Select, Stack, Typography } from "@mui/material";

export interface ListPaginationProps {
  page: number;
  pageSize: number;
  total: number;
  totalPages?: number;
  totalKnown?: boolean;
  loading?: boolean;
  pageSizeOptions?: number[];
  onPageChange: (page: number) => void;
  onPageSizeChange?: (pageSize: number) => void;
}

/** 所有列表统一使用的分页栏；page 为 1-based。 */
export function ListPagination({
  page, pageSize, total, totalPages, loading = false,
  pageSizeOptions = [10, 20, 30], totalKnown = true, onPageChange, onPageSizeChange,
}: ListPaginationProps) {
  if (total <= 0) return null;
  const count = totalPages ?? Math.max(1, Math.ceil(total / pageSize));
  return (
    <Stack direction={{ xs: "column", sm: "row" }} alignItems="center" justifyContent="space-between" spacing={1.5}
      sx={{ px: 2, py: 1.5, borderTop: 1, borderColor: "divider" }}>
      <Stack direction="row" spacing={1} alignItems="center">
        <Typography variant="caption" color="text.secondary">{totalKnown ? `共 ${total} 条` : `已加载至少 ${total} 条`}</Typography>
        {onPageSizeChange && <><Typography variant="caption" color="text.secondary">每页</Typography>
          <FormControl size="small" sx={{ minWidth: 82 }}>
            <Select value={pageSize} onChange={(e) => onPageSizeChange(Number(e.target.value))} disabled={loading} inputProps={{ "aria-label": "每页条数" }}>
              {pageSizeOptions.map((size) => <MenuItem key={size} value={size}>{size} 条</MenuItem>)}
            </Select>
          </FormControl></>}
      </Stack>
      <Pagination count={count} page={Math.min(page, count)} onChange={(_e, value) => onPageChange(value)} color="primary" showFirstButton showLastButton disabled={loading} />
    </Stack>
  );
}
