/**
 * 待分类确认页（DD-19 §9，需要登录）。
 *
 * 列表展示 PENDING_CONFIRMATION 的来源与模型分类候选；
 * 提供：查看详情、确认相关（可人工覆盖分类元数据）、确认无关（来源下线）、重新分类。
 * 确认相关/无关需回传 row_version 乐观锁；冲突时提示刷新重试。
 */
import { useCallback, useEffect, useState } from "react";
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
import CloseIcon from "@mui/icons-material/Close";
import RefreshIcon from "@mui/icons-material/Refresh";
import ReplayIcon from "@mui/icons-material/Replay";
import {
  confirmIrrelevant,
  confirmRelevant,
  listPendingClassification,
  reclassifyPending,
} from "../../api/classificationPending";
import { getErrorMessage } from "../../api/client";
import {
  listCatalogDocumentTypes,
  listCatalogProductForms,
  listCatalogProducts,
  listCatalogVersions,
} from "../../api/catalog";
import { EmptyState } from "../../components/EmptyState";
import { LoadingState } from "../../components/LoadingState";
import { ListPagination } from "../../components/ListPagination";
import { PageHeader } from "../../components/PageHeader";
import type { ConfirmIrrelevantBody, ConfirmRelevantBody, PendingClassification } from "../../types/classificationPending";
import type { CatalogItem, DocumentType, ProductVersion } from "../../types/config";
import { SOURCE_STATUS_META, statusLabel } from "../../types/statusMeta";

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function confidencePct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)}%`;
}

/** 相关性徽标。 */
function RelevanceBadge({ value }: { value: string | null }) {
  if (!value) return <Typography variant="body2" color="text.secondary">—</Typography>;
  if (value === "UNCERTAIN") return <Chip size="small" label="不确定" sx={{ bgcolor: "#fffbe6", color: "#874d00", fontWeight: 600 }} />;
  if (value === "RELEVANT") return <Chip size="small" label="相关" sx={{ bgcolor: "#f6ffed", color: "#237804", fontWeight: 600 }} />;
  return <Chip size="small" label="无关" sx={{ bgcolor: "#f2f3f5", color: "#646a73", fontWeight: 600 }} />;
}

function FormatValue({ value }: { value: unknown }) {
  if (value === null || value === undefined || value === "") return <span style={{ opacity: 0.6 }}>—</span>;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return <>{String(value)}</>;
  }
  return (
    <pre style={{ margin: 0, fontSize: 12, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

interface RelevantForm {
  product_code: string;
  product_version_code: string;
  document_type_code: string;
  product_form_code: string;
  is_domestic: "" | "true" | "false";
  module_name: string;
  business_topic: string;
  summary: string;
  keywords: string;
}

function initialForm(item: PendingClassification): RelevantForm {
  const output = (item.classification?.output ?? {}) as Record<string, unknown>;
  return {
    product_code: String(output.product_code ?? ""),
    product_version_code: String(output.product_version_code ?? ""),
    document_type_code: String(output.document_type_code ?? ""),
    product_form_code: String(output.product_form_code ?? ""),
    is_domestic: output.is_domestic === undefined || output.is_domestic === null ? "" : output.is_domestic ? "true" : "false",
    module_name: String(output.module_name ?? ""),
    business_topic: String(output.business_topic ?? ""),
    summary: String(output.summary ?? ""),
    keywords: Array.isArray(output.keywords) ? (output.keywords as string[]).join("，") : "",
  };
}

function buildRelevantBody(item: PendingClassification, form: RelevantForm): ConfirmRelevantBody {
  const keywords = form.keywords
    .split(/[,，]/)
    .map((s) => s.trim())
    .filter(Boolean);
  return {
    expected_row_version: item.row_version,
    product_code: form.product_code || null,
    product_version_code: form.product_version_code || null,
    document_type_code: form.document_type_code || null,
    product_form_code: form.product_form_code || null,
    is_domestic: form.is_domestic === "" ? null : form.is_domestic === "true",
    module_name: form.module_name.trim() || null,
    business_topic: form.business_topic.trim() || null,
    summary: form.summary.trim() || null,
    keywords: keywords.length > 0 ? keywords : null,
  };
}

export function PendingClassificationPage() {
  const [items, setItems] = useState<PendingClassification[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [page, setPage] = useState(1); const [pageSize, setPageSize] = useState(10); const [total, setTotal] = useState(0);

  const load = useCallback(async (nextPage = 1, nextSize = pageSize) => {
    setLoading(true);
    setError(null);
    try {
      const data = await listPendingClassification({ limit: nextSize, offset: (nextPage - 1) * nextSize });
      setItems(data.items);
      setTotal(data.total); setPage(nextPage);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [pageSize]);

  useEffect(() => {
    void load();
  }, [load]);

  // ---- 详情抽屉 ----
  const [detail, setDetail] = useState<PendingClassification | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const openDetail = (item: PendingClassification) => {
    setDetail(item);
    setDetailOpen(true);
  };
  const closeDetail = () => {
    setDetailOpen(false);
    setDetail(null);
  };

  // ---- 确认相关对话框 ----
  const [relevantItem, setRelevantItem] = useState<PendingClassification | null>(null);
  const [form, setForm] = useState<RelevantForm | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [products, setProducts] = useState<CatalogItem[]>([]);
  const [docTypes, setDocTypes] = useState<DocumentType[]>([]);
  const [productForms, setProductForms] = useState<CatalogItem[]>([]);
  const [versions, setVersions] = useState<ProductVersion[]>([]);

  const loadVersionsFor = async (prods: CatalogItem[], productCode: string) => {
    const product = prods.find((p) => p.code === productCode);
    if (!product) {
      setVersions([]);
      return;
    }
    const v = await listCatalogVersions(product.id);
    setVersions(v.items);
  };

  const loadTaxonomy = async (productCode: string) => {
    const [p, t, f] = await Promise.all([
      listCatalogProducts(),
      listCatalogDocumentTypes(),
      listCatalogProductForms(),
    ]);
    setProducts(p.items);
    setDocTypes(t.items);
    setProductForms(f.items);
    await loadVersionsFor(p.items, productCode);
  };

  const openRelevant = async (item: PendingClassification) => {
    setFormError(null);
    setRelevantItem(item);
    const init = initialForm(item);
    setForm(init);
    try {
      await loadTaxonomy(init.product_code);
    } catch (err) {
      setFormError(getErrorMessage(err, "加载目录选项失败"));
    }
  };

  const onProductChange = async (code: string) => {
    setForm((prev) => (prev ? { ...prev, product_code: code, product_version_code: "" } : prev));
    await loadVersionsFor(products, code);
  };

  const submitRelevant = async () => {
    if (!relevantItem || !form) return;
    setSubmitting(true);
    setFormError(null);
    try {
      await confirmRelevant(relevantItem.version_id, buildRelevantBody(relevantItem, form));
      setNotice(`「${relevantItem.source_name}」已确认相关，进入分块与索引。`);
      setRelevantItem(null);
      setForm(null);
      await load();
    } catch (err) {
      setFormError(getErrorMessage(err, "确认相关失败"));
    } finally {
      setSubmitting(false);
    }
  };

  // ---- 确认无关对话框 ----
  const [irrelevantItem, setIrrelevantItem] = useState<PendingClassification | null>(null);
  const [reason, setReason] = useState("");
  const [irrelevantSubmitting, setIrrelevantSubmitting] = useState(false);
  const [irrelevantError, setIrrelevantError] = useState<string | null>(null);

  const submitIrrelevant = async () => {
    if (!irrelevantItem) return;
    setIrrelevantSubmitting(true);
    setIrrelevantError(null);
    const body: ConfirmIrrelevantBody = {
      expected_row_version: irrelevantItem.row_version,
      reason: reason.trim() || null,
    };
    try {
      await confirmIrrelevant(irrelevantItem.version_id, body);
      setNotice(`「${irrelevantItem.source_name}」已确认无关，来源下线。`);
      setIrrelevantItem(null);
      setReason("");
      await load();
    } catch (err) {
      setIrrelevantError(getErrorMessage(err, "确认无关失败"));
    } finally {
      setIrrelevantSubmitting(false);
    }
  };

  // ---- 重新分类 ----
  const [reclassifyingId, setReclassifyingId] = useState<string | null>(null);
  const doReclassify = async (item: PendingClassification) => {
    setError(null);
    setReclassifyingId(item.version_id);
    try {
      await reclassifyPending(item.version_id);
      setNotice(`「${item.source_name}」已重新安排分类，将用当前配置重跑。`);
      await load();
    } catch (err) {
      setError(err);
    } finally {
      setReclassifyingId(null);
    }
  };

  return (
    <>
      <PageHeader
        title="待分类确认"
        description="人工确认文档分类结果：确认相关后进入分块与索引，确认无关后来源下线；可查看模型理由或重新分类。"
        actions={
          <Button variant="outlined" startIcon={<RefreshIcon />} onClick={() => void load()} disabled={loading}>
            刷新
          </Button>
        }
      />
      {notice && (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice(null)}>
          {notice}
        </Alert>
      )}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {getErrorMessage(error, "加载失败")}
        </Alert>
      )}

      <Card>
        <CardContent sx={{ p: 0 }}>
          {loading && items.length === 0 ? (
            <Box sx={{ p: 6 }}>
              <LoadingState label="正在加载待确认列表…" />
            </Box>
          ) : items.length === 0 ? (
            <Box sx={{ p: 6 }}>
              <EmptyState title="暂无待确认文档" description="所有文档分类结果已确认，无需人工介入。" />
            </Box>
          ) : (
            <TableContainer>
              <Table size="small" sx={{ minWidth: 900 }}>
                <TableHead>
                  <TableRow>
                    <TableCell sx={{ fontWeight: 700 }}>来源</TableCell>
                    <TableCell sx={{ fontWeight: 700 }}>类型 / 版本</TableCell>
                    <TableCell sx={{ fontWeight: 700 }}>模型判断</TableCell>
                    <TableCell sx={{ fontWeight: 700 }}>理由</TableCell>
                    <TableCell sx={{ fontWeight: 700 }}>操作</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {items.map((item) => (
                    <TableRow key={item.version_id} hover>
                      <TableCell sx={{ py: 1.5 }}>
                        <Typography variant="body2" fontWeight={600}>
                          {item.source_name}
                        </Typography>
                        <Typography variant="caption" color="text.secondary" sx={{ fontFamily: "monospace" }}>
                          {item.canonical_key}
                        </Typography>
                      </TableCell>
                      <TableCell sx={{ py: 1.5 }}>
                        <Typography variant="body2">{item.source_type}</Typography>
                        <Typography variant="caption" color="text.secondary">
                          v{item.version_no} · {confidencePct(item.classification?.relevance_confidence)}
                        </Typography>
                      </TableCell>
                      <TableCell sx={{ py: 1.5 }}>
                        <RelevanceBadge value={item.classification?.relevance ?? null} />
                      </TableCell>
                      <TableCell sx={{ py: 1.5 }}>
                        <Typography
                          variant="body2"
                          color="text.secondary"
                          sx={{ maxWidth: 340, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                        >
                          {item.classification?.reason_summary ?? "—"}
                        </Typography>
                      </TableCell>
                      <TableCell sx={{ py: 1.5 }}>
                        <Stack direction="row" spacing={0.75}>
                          <Button size="small" onClick={() => openDetail(item)}>
                            详情
                          </Button>
                          <Button size="small" variant="contained" color="primary" onClick={() => void openRelevant(item)}>
                            确认相关
                          </Button>
                          <Button
                            size="small"
                            variant="outlined"
                            color="error"
                            onClick={() => {
                              setIrrelevantError(null);
                              setReason("");
                              setIrrelevantItem(item);
                            }}
                          >
                            确认无关
                          </Button>
                          <IconButton
                            size="small"
                            title="重新分类"
                            onClick={() => void doReclassify(item)}
                            disabled={reclassifyingId === item.version_id}
                          >
                            {reclassifyingId === item.version_id ? <CircularProgress size={16} /> : <ReplayIcon fontSize="small" />}
                          </IconButton>
                        </Stack>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </CardContent>
      </Card>
      <ListPagination page={page} pageSize={pageSize} total={total} loading={loading} onPageChange={(value) => void load(value)} onPageSizeChange={(value) => { setPageSize(value); void load(1, value); }} />

      {/* 详情抽屉 */}
      <Drawer anchor="right" open={detailOpen} onClose={closeDetail}>
        <Box sx={{ width: { xs: "100vw", sm: 480 }, display: "flex", flexDirection: "column", height: "100%" }}>
          <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ px: 2.5, py: 2, borderBottom: 1, borderColor: "divider" }}>
            <Box>
              <Typography variant="overline" color="text.secondary">分类详情</Typography>
              <Typography variant="h6" sx={{ fontSize: 15 }}>{detail?.source_name}</Typography>
            </Box>
            <IconButton onClick={closeDetail} aria-label="关闭"><CloseIcon /></IconButton>
          </Stack>
          <Box sx={{ flexGrow: 1, overflowY: "auto", px: 2.5, py: 2 }}>
            {detail ? (
              <Stack spacing={2.5}>
                <Box sx={{ bgcolor: "action.hover", borderRadius: 2, p: 2 }}>
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                    <RelevanceBadge value={detail.classification?.relevance ?? null} />
                    <Chip size="small" label={`置信度 ${confidencePct(detail.classification?.relevance_confidence)}`} />
                  </Stack>
                  <Typography variant="body2">{detail.classification?.reason_summary ?? "无分类理由"}</Typography>
                </Box>
                <Box>
                  <Typography variant="overline" color="text.secondary">来源与版本</Typography>
                  <Stack spacing={0.75} sx={{ mt: 0.5 }}>
                    {[
                      ["来源 ID", detail.source_id],
                      ["来源类型", detail.source_type],
                      ["canonical_key", detail.canonical_key],
                      ["版本号", `v${detail.version_no}`],
                      ["版本状态", statusLabel(SOURCE_STATUS_META, detail.version_status).label],
                      ["row_version", String(detail.row_version)],
                    ].map(([label, value]) => (
                      <Stack key={label} direction="row" spacing={2} sx={{ justifyContent: "space-between" }}>
                        <Typography variant="body2" color="text.secondary" sx={{ flexShrink: 0 }}>{label}</Typography>
                        <Typography variant="body2" sx={{ textAlign: "right", wordBreak: "break-all", fontFamily: "monospace" }}>{value}</Typography>
                      </Stack>
                    ))}
                  </Stack>
                </Box>
                <Divider />
                <Box>
                  <Typography variant="overline" color="text.secondary">模型候选元数据</Typography>
                  <Stack spacing={0.75} sx={{ mt: 0.5 }}>
                    {Object.entries(detail.classification?.output ?? {}).map(([key, value]) => (
                      <Stack key={key} direction="row" spacing={2} sx={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                        <Typography variant="body2" color="text.secondary" sx={{ flexShrink: 0 }}>{key}</Typography>
                        <Box sx={{ textAlign: "right" }}><FormatValue value={value} /></Box>
                      </Stack>
                    ))}
                  </Stack>
                </Box>
                {detail.classification?.missing_fields?.length ? (
                  <>
                    <Divider />
                    <Box>
                      <Typography variant="overline" color="text.secondary">缺失字段</Typography>
                      <Stack direction="row" spacing={0.5} flexWrap="wrap" sx={{ mt: 0.5 }}>
                        {detail.classification.missing_fields.map((f) => (
                          <Chip key={f} size="small" variant="outlined" label={f} />
                        ))}
                      </Stack>
                    </Box>
                  </>
                ) : null}
                <Divider />
                <Box>
                  <Typography variant="overline" color="text.secondary">模型配置</Typography>
                  <Stack spacing={0.75} sx={{ mt: 0.5 }}>
                    {[
                      ["model_key", detail.classification?.model_key ?? "—"],
                      ["config_revision", String(detail.classification?.config_revision ?? "—")],
                      ["created_at", formatTime(detail.classification?.created_at ?? null)],
                    ].map(([label, value]) => (
                      <Stack key={label} direction="row" spacing={2} sx={{ justifyContent: "space-between" }}>
                        <Typography variant="body2" color="text.secondary" sx={{ flexShrink: 0 }}>{label}</Typography>
                        <Typography variant="body2" sx={{ textAlign: "right", wordBreak: "break-all", fontFamily: "monospace" }}>{value}</Typography>
                      </Stack>
                    ))}
                  </Stack>
                </Box>
              </Stack>
            ) : null}
          </Box>
          <Stack direction="row" spacing={1} justifyContent="flex-end" sx={{ px: 2.5, py: 2, borderTop: 1, borderColor: "divider" }}>
            <Button variant="contained" onClick={closeDetail}>关闭</Button>
          </Stack>
        </Box>
      </Drawer>

      {/* 确认相关对话框 */}
      <Dialog open={relevantItem !== null} onClose={() => !submitting && setRelevantItem(null)} maxWidth="sm" fullWidth>
        <DialogTitle>确认相关 — {relevantItem?.source_name}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <Typography variant="body2" color="text.secondary">
              确认该文档与平台知识相关，将进入分块与索引。以下字段沿用模型候选值，可人工覆盖；留空则使用模型建议。
            </Typography>
            {formError && <Alert severity="error">{formError}</Alert>}
            {form && (
              <>
                <TextField select size="small" label="产品" value={form.product_code} onChange={(e) => void onProductChange(e.target.value)}>
                  <MenuItem value="">（沿用模型）</MenuItem>
                  {products.map((p) => <MenuItem key={p.id} value={p.code}>{p.name}（{p.code}）</MenuItem>)}
                </TextField>
                <TextField select size="small" label="产品版本" value={form.product_version_code} onChange={(e) => setForm({ ...form, product_version_code: e.target.value })}>
                  <MenuItem value="">（沿用模型）</MenuItem>
                  {versions.map((v) => <MenuItem key={v.id} value={v.version_code}>{v.version_code}</MenuItem>)}
                </TextField>
                <TextField select size="small" label="文档类型" value={form.document_type_code} onChange={(e) => setForm({ ...form, document_type_code: e.target.value })}>
                  <MenuItem value="">（沿用模型）</MenuItem>
                  {docTypes.map((t) => <MenuItem key={t.id} value={t.code}>{t.name}（{t.code}）</MenuItem>)}
                </TextField>
                <TextField select size="small" label="产品形态" value={form.product_form_code} onChange={(e) => setForm({ ...form, product_form_code: e.target.value })}>
                  <MenuItem value="">（沿用模型）</MenuItem>
                  {productForms.map((f) => <MenuItem key={f.id} value={f.code}>{f.name}（{f.code}）</MenuItem>)}
                </TextField>
                <TextField select size="small" label="是否国产" value={form.is_domestic} onChange={(e) => setForm({ ...form, is_domestic: e.target.value as RelevantForm["is_domestic"] })}>
                  <MenuItem value="">（沿用模型）</MenuItem>
                  <MenuItem value="true">是</MenuItem>
                  <MenuItem value="false">否</MenuItem>
                </TextField>
                <TextField size="small" label="模块名称" value={form.module_name} onChange={(e) => setForm({ ...form, module_name: e.target.value })} />
                <TextField size="small" label="业务主题" value={form.business_topic} onChange={(e) => setForm({ ...form, business_topic: e.target.value })} />
                <TextField size="small" label="摘要" multiline minRows={2} value={form.summary} onChange={(e) => setForm({ ...form, summary: e.target.value })} />
                <TextField size="small" label="关键词（逗号分隔）" value={form.keywords} onChange={(e) => setForm({ ...form, keywords: e.target.value })} />
              </>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRelevantItem(null)} disabled={submitting}>取消</Button>
          <Button variant="contained" onClick={() => void submitRelevant()} disabled={submitting || !form}>
            {submitting ? <CircularProgress size={18} /> : "确认相关"}
          </Button>
        </DialogActions>
      </Dialog>

      {/* 确认无关对话框 */}
      <Dialog open={irrelevantItem !== null} onClose={() => !irrelevantSubmitting && setIrrelevantItem(null)} maxWidth="xs" fullWidth>
        <DialogTitle>确认无关 — {irrelevantItem?.source_name}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <Typography variant="body2" color="text.secondary">
              确认该文档与平台知识无关，来源将下线且不再进入索引。
            </Typography>
            {irrelevantError && <Alert severity="error">{irrelevantError}</Alert>}
            <TextField size="small" label="下线原因" value={reason} onChange={(e) => setReason(e.target.value)} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setIrrelevantItem(null)} disabled={irrelevantSubmitting}>取消</Button>
          <Button variant="outlined" color="error" onClick={() => void submitIrrelevant()} disabled={irrelevantSubmitting}>
            {irrelevantSubmitting ? <CircularProgress size={18} /> : "确认无关并下线"}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
