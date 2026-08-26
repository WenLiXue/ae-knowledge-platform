import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import {
  adminCreateDocumentType,
  adminCreateProduct,
  adminCreateProductForm,
  adminCreateVersion,
  adminDeleteDocumentType,
  adminDeleteProduct,
  adminDeleteProductForm,
  adminDeleteVersion,
  adminListDocumentTypes,
  adminListProductForms,
  adminListProducts,
  adminListSourcePriorities,
  adminListVersions,
  adminSetDocumentTypeStatus,
  adminSetProductFormStatus,
  adminSetProductStatus,
  adminSetVersionStatus,
  adminUpdateDocumentType,
  adminUpdateProduct,
  adminUpdateProductForm,
  adminUpdateSourcePriorities,
  adminUpdateVersion,
} from "../../api/catalog";
import { getErrorMessage } from "../../api/client";
import { EmptyState } from "../../components/EmptyState";
import { ErrorAlert } from "../../components/ErrorAlert";
import { LoadingState } from "../../components/LoadingState";
import { PageHeader } from "../../components/PageHeader";
import type { CatalogItem, DocumentType, ProductVersion, SourcePriority } from "../../types/config";

type Notice = { severity: "info" | "success" | "error"; text: string };

type CatalogKind = "product" | "doc-type" | "form";

const KIND_LABEL: Record<CatalogKind, string> = {
  product: "产品",
  "doc-type": "文档类型",
  form: "产品形态",
};

interface ItemForm {
  name: string;
  code: string;
  sort_order: number;
  description: string;
}

const EMPTY_FORM: ItemForm = { name: "", code: "", sort_order: 0, description: "" };

/** 通用目录 CRUD：产品 / 文档类型 / 产品形态。 */
function CatalogSection({ kind }: { kind: CatalogKind }) {
  const [rows, setRows] = useState<CatalogItem[] | DocumentType[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [dialog, setDialog] = useState<null | { mode: "create" } | { mode: "edit"; row: CatalogItem } | { mode: "delete"; row: CatalogItem }>(null);
  const [form, setForm] = useState<ItemForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const fn =
        kind === "product" ? adminListProducts : kind === "doc-type" ? adminListDocumentTypes : adminListProductForms;
      setRows((await fn()).items);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [kind]);

  useEffect(() => {
    void load();
  }, [load]);

  const openCreate = () => {
    setForm(EMPTY_FORM);
    setDialog({ mode: "create" });
  };

  const openEdit = (row: CatalogItem) => {
    setForm({ name: row.name, code: row.code, sort_order: row.sort_order, description: (row as DocumentType).description ?? "" });
    setDialog({ mode: "edit", row });
  };

  const submit = async () => {
    if (!dialog || saving) return;
    setSaving(true);
    setNotice(null);
    try {
      const payload = {
        name: form.name,
        code: form.code,
        sort_order: form.sort_order,
        ...(kind === "doc-type" ? { description: form.description } : {}),
      };
      if (dialog.mode === "create") {
        const fn = kind === "product" ? adminCreateProduct : kind === "doc-type" ? adminCreateDocumentType : adminCreateProductForm;
        await fn(payload);
        setNotice({ severity: "success", text: "已新增。" });
      } else {
        const fn = kind === "product" ? adminUpdateProduct : kind === "doc-type" ? adminUpdateDocumentType : adminUpdateProductForm;
        await fn(dialog.row.id, payload);
        setNotice({ severity: "success", text: "已更新。" });
      }
      setDialog(null);
      await load();
    } catch (err) {
      setNotice({ severity: "error", text: getErrorMessage(err, "保存失败。") });
    } finally {
      setSaving(false);
    }
  };

  const submitDelete = async () => {
    if (!dialog || dialog.mode !== "delete" || saving) return;
    setSaving(true);
    setNotice(null);
    try {
      const fn = kind === "product" ? adminDeleteProduct : kind === "doc-type" ? adminDeleteDocumentType : adminDeleteProductForm;
      await fn(dialog.row.id);
      setDialog(null);
      setNotice({ severity: "success", text: `已删除${KIND_LABEL[kind]}“${dialog.row.name}”。` });
      await load();
    } catch (err) {
      setNotice({ severity: "error", text: getErrorMessage(err, "删除失败；如果该配置已被使用，请改用停用。") });
    } finally {
      setSaving(false);
    }
  };

  const toggle = async (row: CatalogItem) => {
    const target = row.status === "ENABLED" ? "DISABLED" : "ENABLED";
    const fn = kind === "product" ? adminSetProductStatus : kind === "doc-type" ? adminSetDocumentTypeStatus : adminSetProductFormStatus;
    try {
      await fn(row.id, target);
      await load();
    } catch (err) {
      setNotice({ severity: "error", text: getErrorMessage(err, "操作失败。") });
    }
  };

  return (
    <Stack spacing={2}>
      <Box>
        <Button variant="contained" onClick={openCreate}>新增{KIND_LABEL[kind]}</Button>
      </Box>
      {notice && <Alert severity={notice.severity}>{notice.text}</Alert>}
      {error ? (
        <ErrorAlert error={error} onRetry={() => void load()} title="加载失败" />
      ) : loading ? (
        <LoadingState label="加载中…" />
      ) : rows.length === 0 ? (
        <EmptyState title={`暂无${KIND_LABEL[kind]}`} description="点击右上角“新增”创建。" />
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>名称</TableCell>
              <TableCell>code</TableCell>
              <TableCell>状态</TableCell>
              <TableCell>排序</TableCell>
              <TableCell align="right">操作</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.id}>
                <TableCell>{row.name}</TableCell>
                <TableCell>{row.code}</TableCell>
                <TableCell>
                  {row.status === "ENABLED" ? (
                    <Typography variant="body2" color="text.secondary">启用</Typography>
                  ) : (
                    <Chip size="small" label="已停用" color="default" variant="outlined" />
                  )}
                </TableCell>
                <TableCell>{row.sort_order}</TableCell>
                <TableCell align="right">
                  <Button size="small" onClick={() => openEdit(row)}>编辑</Button>
                  <Button size="small" color={row.status === "ENABLED" ? "error" : "primary"} onClick={() => void toggle(row)}>
                    {row.status === "ENABLED" ? "停用" : "启用"}
                  </Button>
                  <Button size="small" color="error" onClick={() => setDialog({ mode: "delete", row })}>
                    删除
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <Dialog open={dialog !== null} onClose={() => setDialog(null)} fullWidth maxWidth="sm">
        <DialogTitle>{dialog?.mode === "create" ? `新增${KIND_LABEL[kind]}` : dialog?.mode === "delete" ? `删除${KIND_LABEL[kind]}` : `编辑${KIND_LABEL[kind]}`}</DialogTitle>
        <DialogContent>
          {dialog?.mode === "delete" ? (
            <Typography sx={{ pt: 1 }}>
              确定删除“{dialog.row.name}”吗？如果该配置已被版本、文档或任务引用，系统会拒绝删除并保留数据。
            </Typography>
          ) : (
          <Stack spacing={2} sx={{ pt: 1 }}>
            <TextField size="small" label="名称" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <TextField size="small" label="code" value={form.code} disabled={dialog?.mode === "edit"} onChange={(e) => setForm({ ...form, code: e.target.value })} helperText="code 唯一，创建后不可修改" />
            <TextField size="small" label="排序" type="number" value={form.sort_order} onChange={(e) => setForm({ ...form, sort_order: Number(e.target.value) })} />
            {kind === "doc-type" && (
              <TextField size="small" label="描述" multiline minRows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            )}
          </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialog(null)}>取消</Button>
          {dialog?.mode === "delete" ? (
            <Button variant="contained" color="error" disabled={saving} onClick={() => void submitDelete()}>{saving ? "删除中…" : "确认删除"}</Button>
          ) : (
            <Button variant="contained" disabled={saving || !form.name} onClick={() => void submit()}>{saving ? "保存中…" : "保存"}</Button>
          )}
        </DialogActions>
      </Dialog>
    </Stack>
  );
}

/** 产品版本管理。 */
function VersionsSection({ product }: { product: CatalogItem }) {
  const [rows, setRows] = useState<ProductVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialog, setDialog] = useState<null | { mode: "create" } | { mode: "edit"; row: ProductVersion }>(null);
  const [form, setForm] = useState({ version_code: "", major_version: "", minor_version: "", sort_order: 0 });
  const [notice, setNotice] = useState<Notice | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows((await adminListVersions(product.id)).items);
    } finally {
      setLoading(false);
    }
  }, [product.id]);

  useEffect(() => {
    void load();
  }, [load]);

  const submit = async () => {
    if (!dialog) return;
    try {
      const payload = {
        version_code: form.version_code,
        major_version: form.major_version === "" ? null : Number(form.major_version),
        minor_version: form.minor_version === "" ? null : Number(form.minor_version),
        sort_order: Number(form.sort_order),
      };
      if (dialog.mode === "create") await adminCreateVersion(product.id, payload);
      else await adminUpdateVersion(dialog.row.id, payload);
      setNotice({ severity: "success", text: "已保存。" });
      setDialog(null);
      await load();
    } catch (err) {
      setNotice({ severity: "error", text: getErrorMessage(err, "保存失败。") });
    }
  };

  const deleteVersion = async (row: ProductVersion) => {
    if (!window.confirm(`确定删除版本“${row.version_code}”吗？如果已被知识来源或任务引用，系统会拒绝删除。`)) return;
    try {
      await adminDeleteVersion(row.id);
      setNotice({ severity: "success", text: `版本“${row.version_code}”已删除。` });
      await load();
    } catch (err) {
      setNotice({ severity: "error", text: getErrorMessage(err, "删除失败；如果该版本已被使用，请改用停用。") });
    }
  };

  return (
    <Stack spacing={1.5}>
      <Stack direction="row" spacing={1} alignItems="center">
        <Typography variant="subtitle2">{product.name} 的版本</Typography>
        <Button size="small" variant="outlined" onClick={() => { setForm({ version_code: "", major_version: "", minor_version: "", sort_order: 0 }); setDialog({ mode: "create" }); }}>
          新增版本
        </Button>
      </Stack>
      {notice && <Alert severity={notice.severity}>{notice.text}</Alert>}
      {loading ? (
        <LoadingState label="加载版本…" />
      ) : rows.length === 0 ? (
        <Typography color="text.secondary" variant="body2">暂无版本。</Typography>
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>版本号</TableCell>
              <TableCell>大/小版本</TableCell>
              <TableCell>状态</TableCell>
              <TableCell align="right">操作</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.id}>
                <TableCell>{row.version_code}</TableCell>
                <TableCell>{row.major_version ?? "-"} / {row.minor_version ?? "-"}</TableCell>
                <TableCell>
                  {row.status === "ENABLED" ? (
                    <Typography variant="body2" color="text.secondary">启用</Typography>
                  ) : (
                    <Chip size="small" label="已停用" color="default" variant="outlined" />
                  )}
                </TableCell>
                <TableCell align="right">
                  <Button size="small" onClick={() => { setForm({ version_code: row.version_code, major_version: String(row.major_version ?? ""), minor_version: String(row.minor_version ?? ""), sort_order: row.sort_order }); setDialog({ mode: "edit", row }); }}>编辑</Button>
                  <Button size="small" color={row.status === "ENABLED" ? "error" : "primary"} onClick={async () => { await adminSetVersionStatus(row.id, row.status === "ENABLED" ? "DISABLED" : "ENABLED"); await load(); }}>
                    {row.status === "ENABLED" ? "停用" : "启用"}
                  </Button>
                  <Button size="small" color="error" onClick={() => void deleteVersion(row)}>
                    删除
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <Dialog open={dialog !== null} onClose={() => setDialog(null)} fullWidth maxWidth="sm">
        <DialogTitle>{dialog?.mode === "create" ? "新增版本" : "编辑版本"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <TextField size="small" label="版本号（如 1.0）" value={form.version_code} onChange={(e) => setForm({ ...form, version_code: e.target.value })} />
            <Stack direction="row" spacing={2}>
              <TextField size="small" label="大版本" type="number" value={form.major_version} onChange={(e) => setForm({ ...form, major_version: e.target.value })} />
              <TextField size="small" label="小版本" type="number" value={form.minor_version} onChange={(e) => setForm({ ...form, minor_version: e.target.value })} />
            </Stack>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialog(null)}>取消</Button>
          <Button variant="contained" disabled={!form.version_code} onClick={() => void submit()}>保存</Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}

/** 来源优先级。 */
function SourcePrioritiesSection() {
  const [rows, setRows] = useState<SourcePriority[]>([]);
  const [values, setValues] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<Notice | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const items = (await adminListSourcePriorities()).items;
      setRows(items);
      setValues(Object.fromEntries(items.map((item) => [item.source_code, item.priority])));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    try {
      const items = rows.map((row) => ({ source_code: row.source_code, priority: values[row.source_code] }));
      await adminUpdateSourcePriorities(items);
      setNotice({ severity: "success", text: "优先级已保存。" });
    } catch (err) {
      setNotice({ severity: "error", text: getErrorMessage(err, "保存失败。") });
    }
  };

  return (
    <Stack spacing={2}>
      {notice && <Alert severity={notice.severity}>{notice.text}</Alert>}
      {loading ? (
        <LoadingState label="加载来源优先级…" />
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>来源</TableCell>
              <TableCell>优先级（越小越高）</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.source_code}>
                <TableCell>{row.display_name}</TableCell>
                <TableCell>
                  <TextField size="small" type="number" value={values[row.source_code] ?? row.priority}
                    onChange={(e) => setValues({ ...values, [row.source_code]: Number(e.target.value) })}
                    inputProps={{ min: 1 }} sx={{ width: 120 }} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <Box>
        <Button variant="contained" onClick={() => void save()}>保存优先级</Button>
      </Box>
    </Stack>
  );
}

interface ProductForm {
  name: string;
  code: string;
  sort_order: number;
}

const EMPTY_PRODUCT_FORM: ProductForm = { name: "", code: "", sort_order: 0 };

/** 知识库配置页：产品/版本、文档类型、产品形态、来源优先级。 */
export function KnowledgeConfigPage() {
  const [tab, setTab] = useState(0);
  const [products, setProducts] = useState<CatalogItem[]>([]);
  const [productLoading, setProductLoading] = useState(true);
  const [selectedProduct, setSelectedProduct] = useState<CatalogItem | null>(null);
  const [productNotice, setProductNotice] = useState<Notice | null>(null);
  const [productDialog, setProductDialog] = useState<null | { mode: "create" } | { mode: "edit"; product: CatalogItem }>(null);
  const [productForm, setProductForm] = useState<ProductForm>(EMPTY_PRODUCT_FORM);
  const [productSaving, setProductSaving] = useState(false);

  const openProductCreate = () => {
    setProductForm(EMPTY_PRODUCT_FORM);
    setProductDialog({ mode: "create" });
  };

  const openProductEdit = (product: CatalogItem) => {
    setProductForm({ name: product.name, code: product.code, sort_order: product.sort_order });
    setProductDialog({ mode: "edit", product });
  };

  const submitProduct = async () => {
    if (!productDialog || productSaving) return;
    setProductSaving(true);
    setProductNotice(null);
    try {
      const payload = { name: productForm.name, code: productForm.code, sort_order: productForm.sort_order };
      if (productDialog.mode === "create") {
        const created = await adminCreateProduct(payload);
        setProducts((current) => [...current, created]);
        setSelectedProduct(created);
        setProductNotice({ severity: "success", text: `产品“${created.name}”已新增。` });
      } else {
        const updated = await adminUpdateProduct(productDialog.product.id, payload);
        setProducts((current) => current.map((item) => (item.id === updated.id ? updated : item)));
        setSelectedProduct((current) => (current?.id === updated.id ? updated : current));
        setProductNotice({ severity: "success", text: `产品“${updated.name}”已更新。` });
      }
      setProductDialog(null);
    } catch (err) {
      setProductNotice({ severity: "error", text: getErrorMessage(err, "保存失败。") });
    } finally {
      setProductSaving(false);
    }
  };

  const deleteProduct = async (product: CatalogItem) => {
    if (!window.confirm(`确定删除产品“${product.name}”吗？产品下存在版本或其他引用时将无法删除。`)) return;
    try {
      await adminDeleteProduct(product.id);
      setProducts((current) => current.filter((item) => item.id !== product.id));
      setSelectedProduct((current) => (current?.id === product.id ? null : current));
      setProductNotice({ severity: "success", text: `产品“${product.name}”已删除。` });
    } catch (err) {
      setProductNotice({ severity: "error", text: getErrorMessage(err, "删除失败；如果产品已被使用，请改用停用。") });
    }
  };

  useEffect(() => {
    adminListProducts().then((res) => {
      setProducts(res.items);
      setSelectedProduct((current) => current ?? res.items[0] ?? null);
    }).finally(() => setProductLoading(false));
  }, []);

  return (
    <>
      <PageHeader title="知识库配置" description="管理产品、版本、文档类型、产品形态与来源优先级。" />
      <Card>
        <CardContent sx={{ p: { xs: 1, sm: 2 } }}>
          <Tabs value={tab} onChange={(_e, value) => setTab(value)}>
            <Tab label="产品与版本" />
            <Tab label="文档类型" />
            <Tab label="产品形态" />
            <Tab label="来源优先级" />
          </Tabs>
          <Box sx={{ pt: 2 }}>
            {tab === 0 && (
              <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
                <Box sx={{ minWidth: { md: 260 } }}>
                  <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
                    <Button variant="contained" size="small" onClick={openProductCreate}>新增产品</Button>
                  </Stack>
                  {productNotice && <Alert severity={productNotice.severity} sx={{ mb: 1 }}>{productNotice.text}</Alert>}
                  {productLoading ? (
                    <LoadingState label="加载产品…" />
                  ) : products.length === 0 ? (
                    <Typography color="text.secondary">暂无产品，点击上方“新增产品”创建。</Typography>
                  ) : (
                    <Stack spacing={0.5}>
                      {products.map((p) => {
                        const selected = selectedProduct?.id === p.id;
                        return (
                          <Stack
                            key={p.id}
                            direction="row"
                            spacing={0.5}
                            alignItems="center"
                            onClick={() => setSelectedProduct(p)}
                            sx={{
                              px: 1.25,
                              py: 0.75,
                              borderRadius: 1,
                              cursor: "pointer",
                              bgcolor: selected ? "action.selected" : "transparent",
                              "&:hover": { bgcolor: selected ? "action.selected" : "action.hover" },
                            }}
                          >
                            <Typography
                              variant="body2"
                              fontWeight={selected ? 600 : 400}
                              noWrap
                              sx={{ flex: 1, minWidth: 0 }}
                            >
                              {p.name}
                            </Typography>
                            {p.status !== "ENABLED" && (
                              <Chip size="small" label="已停用" color="default" variant="outlined" />
                            )}
                            <Button size="small" onClick={(event) => { event.stopPropagation(); openProductEdit(p); }}>
                              编辑
                            </Button>
                            <Button size="small" color="error" onClick={(event) => { event.stopPropagation(); void deleteProduct(p); }}>
                              删除
                            </Button>
                          </Stack>
                        );
                      })}
                    </Stack>
                  )}
                </Box>
                <Box sx={{ flex: 1 }}>
                  {selectedProduct ? <VersionsSection product={selectedProduct} /> : <Typography color="text.secondary">选择左侧产品查看版本。</Typography>}
                </Box>
              </Stack>
            )}
            {tab === 1 && <CatalogSection kind="doc-type" />}
            {tab === 2 && <CatalogSection kind="form" />}
            {tab === 3 && <SourcePrioritiesSection />}
          </Box>
        </CardContent>
      </Card>

      <Dialog open={productDialog !== null} onClose={() => setProductDialog(null)} fullWidth maxWidth="sm">
        <DialogTitle>{productDialog?.mode === "create" ? "新增产品" : "编辑产品"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <TextField size="small" label="名称" value={productForm.name} onChange={(e) => setProductForm({ ...productForm, name: e.target.value })} />
            <TextField size="small" label="code" value={productForm.code} disabled={productDialog?.mode === "edit"} onChange={(e) => setProductForm({ ...productForm, code: e.target.value })} helperText="code 唯一，创建后不可修改" />
            <TextField size="small" label="排序" type="number" value={productForm.sort_order} onChange={(e) => setProductForm({ ...productForm, sort_order: Number(e.target.value) })} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setProductDialog(null)}>取消</Button>
          <Button variant="contained" disabled={productSaving || !productForm.name || !productForm.code} onClick={() => void submitProduct()}>
            {productSaving ? "保存中…" : "保存"}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
