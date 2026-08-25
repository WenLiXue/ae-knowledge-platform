import { useEffect, useRef, useState, type Ref } from "react";
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
import {
  listCatalogDocumentTypes,
  listCatalogProducts,
  listCatalogVersions,
} from "../../api/catalog";
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

/** 目录选项：筛选下拉/标签只用 id 与展示名，不绑定 Mock code（DD-19 §4.4）。 */
interface CatalogOption {
  id: string;
  name: string;
}

/** 判定是否为请求取消（卸载/切换条件时中止，不视为错误）。 */
function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

/**
 * 知识查询 Composer：问题输入 + 可选查询范围（默认收起）+ 发送。
 * 筛选目录（产品/版本/文档类型）来自真实 catalog API：
 * - 产品与文档类型挂载时加载；产品变化时按需加载版本；
 * - 加载失败保留问题输入，筛选区展示错误与重试；
 * - 已选择但已停用/不存在的历史值展示为“已停用”，不参与新选择。
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

  const [products, setProducts] = useState<CatalogOption[]>([]);
  const [documentTypes, setDocumentTypes] = useState<CatalogOption[]>([]);
  const [versions, setVersions] = useState<CatalogOption[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [retryToken, setRetryToken] = useState(0);

  // 已见过的目录项名称快照：目录停用/刷新期间，已选历史值仍可显示名称而非裸 id。
  const knownNames = useRef<Map<string, string>>(new Map());

  // 初始目录（产品 + 文档类型）加载；卸载时中止，不更新已卸载组件状态。
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setCatalogLoading(true);
    setLoadError(null);
    Promise.all([
      listCatalogProducts(controller.signal),
      listCatalogDocumentTypes(controller.signal),
    ])
      .then(([productList, docTypeList]) => {
        if (!active) return;
        const productItems = productList.items.map((p) => ({ id: p.id, name: p.name }));
        const docItems = docTypeList.items.map((t) => ({ id: t.id, name: t.name }));
        productItems.forEach((p) => knownNames.current.set(p.id, p.name));
        docItems.forEach((t) => knownNames.current.set(t.id, t.name));
        setProducts(productItems);
        setDocumentTypes(docItems);
        setCatalogLoading(false);
      })
      .catch((error) => {
        if (!active || isAbort(error)) return;
        setCatalogLoading(false);
        setLoadError("目录加载失败，请检查网络后重试。");
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [retryToken]);

  // 产品变化时按需加载版本；产品清空/加载失败时清空版本（不阻断提问）。
  useEffect(() => {
    const productId = filters.product_id;
    const controller = new AbortController();
    let active = true;
    if (!productId) {
      setVersions([]);
      setVersionsLoading(false);
      return () => controller.abort();
    }
    setVersionsLoading(true);
    listCatalogVersions(productId, controller.signal)
      .then((list) => {
        if (!active) return;
        const items = list.items.map((v) => ({ id: v.id, name: v.version_code }));
        items.forEach((v) => knownNames.current.set(v.id, v.name));
        setVersions(items);
        setVersionsLoading(false);
      })
      .catch((error) => {
        if (!active || isAbort(error)) return;
        setVersions([]);
        setVersionsLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [filters.product_id]);

  /** 解析已选项名称：当前目录 → 历史快照 → null（表示已停用/不存在）。 */
  function catalogName(id: string, options: CatalogOption[]): string | null {
    return options.find((item) => item.id === id)?.name ?? knownNames.current.get(id) ?? null;
  }

  // 已选条件：以可移除 Chip 呈现；移除产品时同时移除版本。
  // 已停用/不存在的历史值按“已停用”标注，但不作为可选项。
  const chips: { key: string; label: string; disabled: boolean; onRemove: () => void }[] = [];
  if (filters.product_id) {
    const name = catalogName(filters.product_id, products);
    chips.push({
      key: "product",
      label: name ?? filters.product_id,
      disabled: name === null,
      onRemove: () => onFiltersChange({ ...filters, product_id: null, product_version_id: null }),
    });
  }
  if (filters.product_version_id) {
    const name = catalogName(filters.product_version_id, versions);
    chips.push({
      key: "version",
      label: name ?? filters.product_version_id,
      disabled: name === null,
      onRemove: () => onFiltersChange({ ...filters, product_version_id: null }),
    });
  }
  if (filters.document_type_id) {
    const name = catalogName(filters.document_type_id, documentTypes);
    chips.push({
      key: "document-type",
      label: name ?? filters.document_type_id,
      disabled: name === null,
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
              {chip.disabled ? (
                <Typography
                  component="span"
                  sx={{ ml: 0.5, fontSize: 10, fontWeight: 400, color: "text.disabled" }}
                >
                  已停用
                </Typography>
              ) : null}
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
          {catalogLoading ? (
            <Stack
              direction="row"
              alignItems="center"
              gap={1}
              sx={{ gridColumn: { xs: "1", sm: "1 / -1" }, color: "text.secondary" }}
            >
              <CircularProgress size={14} />
              <Typography variant="caption">正在加载目录…</Typography>
            </Stack>
          ) : null}
          {loadError ? (
            <Stack
              direction="row"
              alignItems="center"
              gap={1}
              sx={{ gridColumn: { xs: "1", sm: "1 / -1" } }}
            >
              <Typography variant="caption" color="error">
                {loadError}
              </Typography>
              <Button size="small" variant="text" onClick={() => setRetryToken((token) => token + 1)}>
                重试
              </Button>
            </Stack>
          ) : null}

          <FormControl size="small" fullWidth disabled={catalogLoading}>
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
              {products.map((product) => (
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
              disabled={!filters.product_id || versionsLoading}
            >
              <MenuItem value="">{filters.product_id ? "全部版本" : "请先选择产品"}</MenuItem>
              {versions.map((version) => (
                <MenuItem key={version.id} value={version.id}>
                  {version.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl size="small" fullWidth disabled={catalogLoading}>
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
              {documentTypes.map((type) => (
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
