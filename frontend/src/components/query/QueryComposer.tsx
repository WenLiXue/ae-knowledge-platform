import { useState, type Ref } from "react";
import {
  Box,
  Button,
  CircularProgress,
  FormControl,
  IconButton,
  InputBase,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Typography,
} from "@mui/material";
import ArrowUpwardRoundedIcon from "@mui/icons-material/ArrowUpwardRounded";
import CloseRoundedIcon from "@mui/icons-material/CloseRounded";
import TuneRoundedIcon from "@mui/icons-material/TuneRounded";
import { CATALOG_OPTIONS } from "../../api/conversations";
import type { QueryFilters } from "../../types/conversations";

interface QueryComposerProps {
  question: string;
  filters: QueryFilters;
  submitting: boolean;
  onQuestionChange: (value: string) => void;
  onFiltersChange: (filters: QueryFilters) => void;
  onSubmit: () => void;
  autoFocus?: boolean;
  /** 让父组件可以把焦点移回问题输入框（例如点击示例问题后）。 */
  inputRef?: Ref<HTMLInputElement | HTMLTextAreaElement>;
}

function productName(id: string): string {
  return CATALOG_OPTIONS.products.find((item) => item.id === id)?.name ?? id;
}

function versionName(id: string): string {
  for (const versions of Object.values(CATALOG_OPTIONS.versions)) {
    const found = versions.find((item) => item.id === id);
    if (found) return found.name;
  }
  return id;
}

function documentTypeName(id: string): string {
  return CATALOG_OPTIONS.documentTypes.find((item) => item.id === id)?.name ?? id;
}

/**
 * 知识查询 Composer：问题输入 + 可选查询范围（默认收起）+ 发送。
 * 与 HTML 原型 .composer 的布局逻辑一致，但保持组件级局部样式，
 * 不全局改动 MUI 组件。
 */
export function QueryComposer({
  question,
  filters,
  submitting,
  onQuestionChange,
  onFiltersChange,
  onSubmit,
  autoFocus,
  inputRef,
}: QueryComposerProps) {
  const [scopeOpen, setScopeOpen] = useState(false);

  const availableVersions = filters.product_id
    ? (CATALOG_OPTIONS.versions[filters.product_id] ?? [])
    : [];

  // 已选条件：以可移除 Chip 呈现；移除产品时同时移除版本。
  const chips: { key: string; label: string; onRemove: () => void }[] = [];
  if (filters.product_id) {
    chips.push({
      key: "product",
      label: productName(filters.product_id),
      onRemove: () => onFiltersChange({ ...filters, product_id: null, product_version_id: null }),
    });
  }
  if (filters.product_version_id) {
    chips.push({
      key: "version",
      label: versionName(filters.product_version_id),
      onRemove: () => onFiltersChange({ ...filters, product_version_id: null }),
    });
  }
  if (filters.document_type_id) {
    chips.push({
      key: "document-type",
      label: documentTypeName(filters.document_type_id),
      onRemove: () => onFiltersChange({ ...filters, document_type_id: null }),
    });
  }

  const canSubmit = question.trim().length > 0 && !submitting;

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey) && canSubmit) {
      event.preventDefault();
      onSubmit();
    }
  };

  return (
    <Box
      sx={{
        border: 1,
        borderColor: "divider",
        borderRadius: "16px",
        bgcolor: "background.paper",
        overflow: "hidden",
        transition: "border-color 0.16s ease, box-shadow 0.16s ease",
        "&:focus-within": {
          borderColor: "#aeb3ba",
          boxShadow: "0 3px 16px rgba(32,33,36,0.08)",
        },
      }}
    >
      <Typography
        component="label"
        htmlFor="query-question-input"
        sx={{
          position: "absolute",
          width: 1,
          height: 1,
          overflow: "hidden",
          clip: "rect(0 0 0 0)",
          whiteSpace: "nowrap",
        }}
      >
        知识查询问题
      </Typography>
      <InputBase
        id="query-question-input"
        inputRef={inputRef}
        value={question}
        onChange={(event) => onQuestionChange(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="询问产品规格、部署方式、功能说明或历史案例"
        multiline
        minRows={3}
        maxRows={8}
        autoFocus={autoFocus}
        sx={{
          display: "block",
          width: "100%",
          px: 2,
          pt: 2,
          pb: 1,
          fontSize: 15,
          lineHeight: 1.6,
        }}
      />

      <Stack
        direction="row"
        alignItems="center"
        justifyContent="space-between"
        sx={{ gap: 1, px: 1.25, py: 0.75, minHeight: 52 }}
      >
        <Stack
          direction="row"
          alignItems="center"
          flexWrap="wrap"
          useFlexGap
          sx={{ gap: 0.75, minWidth: 0 }}
        >
          <Button
            size="small"
            onClick={() => setScopeOpen((open) => !open)}
            aria-expanded={scopeOpen}
            aria-controls="query-scope-panel"
            startIcon={<TuneRoundedIcon fontSize="small" />}
            sx={{
              color: scopeOpen ? "text.primary" : "text.secondary",
              fontWeight: 500,
              "&:hover": { bgcolor: "action.hover" },
            }}
          >
            限定范围
          </Button>
          {chips.map((chip) => (
            <Button
              key={chip.key}
              size="small"
              onClick={chip.onRemove}
              aria-label={`移除条件：${chip.label}`}
              endIcon={<CloseRoundedIcon sx={{ fontSize: 14 }} />}
              sx={{
                minHeight: 28,
                minWidth: 0,
                px: 1,
                border: 1,
                borderColor: "divider",
                borderRadius: 1.5,
                bgcolor: "#f7f7f6",
                color: "text.secondary",
                fontSize: 11,
                fontWeight: 500,
                "&:hover": { bgcolor: "#efefed", color: "text.primary" },
              }}
            >
              {chip.label}
            </Button>
          ))}
        </Stack>

        <IconButton
          onClick={onSubmit}
          disabled={!canSubmit}
          aria-label="发送查询"
          sx={{
            width: 36,
            height: 36,
            flex: "0 0 36px",
            borderRadius: 1.5,
            bgcolor: "#202124",
            color: "#fff",
            "&:hover": { bgcolor: "#000" },
            "&:disabled": { bgcolor: "#dedfdf", color: "#a4a6a8" },
          }}
        >
          {submitting ? <CircularProgress size={18} sx={{ color: "inherit" }} /> : <ArrowUpwardRoundedIcon />}
        </IconButton>
      </Stack>

      {scopeOpen && (
        <Box
          id="query-scope-panel"
          role="group"
          aria-label="限定查询范围"
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr", sm: "repeat(3, minmax(0, 1fr))" },
            gap: 1.5,
            mt: 0.5,
            mx: 1.25,
            mb: 1.25,
            p: 1.5,
            border: 1,
            borderColor: "divider",
            borderRadius: 2,
            bgcolor: "background.paper",
          }}
        >
          <FormControl size="small" fullWidth>
            <InputLabel id="query-product-label">产品</InputLabel>
            <Select
              labelId="query-product-label"
              label="产品"
              value={filters.product_id ?? ""}
              onChange={(event) => {
                const productId = event.target.value as string;
                // 产品切换时清空版本。
                onFiltersChange({ ...filters, product_id: productId || null, product_version_id: null });
              }}
            >
              <MenuItem value="">全部产品</MenuItem>
              {CATALOG_OPTIONS.products.map((product) => (
                <MenuItem key={product.id} value={product.id}>
                  {product.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl size="small" fullWidth>
            <InputLabel id="query-version-label">版本</InputLabel>
            <Select
              labelId="query-version-label"
              label="版本"
              value={filters.product_version_id ?? ""}
              onChange={(event) =>
                onFiltersChange({ ...filters, product_version_id: (event.target.value as string) || null })
              }
              disabled={!filters.product_id}
            >
              <MenuItem value="">{filters.product_id ? "全部版本" : "请先选择产品"}</MenuItem>
              {availableVersions.map((version) => (
                <MenuItem key={version.id} value={version.id}>
                  {version.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl size="small" fullWidth>
            <InputLabel id="query-doc-type-label">文档类型</InputLabel>
            <Select
              labelId="query-doc-type-label"
              label="文档类型"
              value={filters.document_type_id ?? ""}
              onChange={(event) =>
                onFiltersChange({ ...filters, document_type_id: (event.target.value as string) || null })
              }
            >
              <MenuItem value="">全部类型</MenuItem>
              {CATALOG_OPTIONS.documentTypes.map((type) => (
                <MenuItem key={type.id} value={type.id}>
                  {type.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </Box>
      )}
    </Box>
  );
}
