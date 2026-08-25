import { useCallback, useEffect, useRef, useState } from "react";
import { useBlocker, useSearchParams } from "react-router-dom";
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
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Switch,
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
import { getErrorMessage } from "../../api/client";
import {
  adminCreateModel,
  adminListModels,
  adminSetModelEnabled,
  adminTestModel,
  adminUpdateModel,
  getServiceBindings,
  saveServiceBindings,
} from "../../api/llmConfig";
import { EmptyState } from "../../components/EmptyState";
import { ErrorAlert } from "../../components/ErrorAlert";
import { LoadingState } from "../../components/LoadingState";
import { PageHeader } from "../../components/PageHeader";
import { ApiError } from "../../types/api";
import type {
  LlmModel,
  LlmModelType,
  ServiceBindings,
  ServiceType,
} from "../../types/config";

type Notice = { severity: "info" | "success" | "error"; text: string; servicesLink?: boolean };

const TYPE_LABEL: Record<LlmModelType, string> = {
  CHAT: "Chat",
  EMBEDDING: "Embedding",
  RERANK: "Rerank",
};

const ALL_SERVICE_TYPES: ServiceType[] = [
  "QA",
  "DOCUMENT_CLASSIFICATION",
  "DOCUMENT_EMBEDDING",
  "RETRIEVAL_RERANK",
];

// 服务类型 → 可绑定模型类型（DD-20 §4.3、§7.2）
const SERVICE_MODEL_TYPE: Record<ServiceType, LlmModelType> = {
  QA: "CHAT",
  DOCUMENT_CLASSIFICATION: "CHAT",
  DOCUMENT_EMBEDDING: "EMBEDDING",
  RETRIEVAL_RERANK: "RERANK",
};

interface ModelForm {
  name: string;
  model_type: LlmModelType;
  provider: string;
  base_url: string;
  model_name: string;
  api_key: string;
  enabled: boolean;
}

const EMPTY_FORM: ModelForm = {
  name: "",
  model_type: "CHAT",
  provider: "openai-compatible",
  base_url: "",
  model_name: "",
  api_key: "",
  enabled: true,
};

function isConflict(error: unknown, code: string): boolean {
  return error instanceof ApiError && error.code === code;
}

// ---- Tab 一：模型管理 ----

function ModelsTab({ onGoToServices }: { onGoToServices: () => void }) {
  const [revision, setRevision] = useState<number | null>(null);
  const [models, setModels] = useState<LlmModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [dialog, setDialog] = useState<null | { mode: "create" } | { mode: "edit"; row: LlmModel }>(null);
  const [form, setForm] = useState<ModelForm>(EMPTY_FORM);
  const [hasKey, setHasKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await adminListModels();
      setModels(data.items);
      setRevision(data.revision);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const openCreate = () => {
    setForm(EMPTY_FORM);
    setHasKey(false);
    setDialog({ mode: "create" });
  };

  const openEdit = (row: LlmModel) => {
    setForm({
      name: row.name,
      model_type: row.model_type,
      provider: row.provider,
      base_url: row.base_url,
      model_name: row.model_name,
      api_key: "",
      enabled: row.enabled,
    });
    setHasKey(row.has_api_key);
    setDialog({ mode: "edit", row });
  };

  const submit = async () => {
    if (!dialog || saving) return;
    setSaving(true);
    setNotice(null);
    try {
      const payload = {
        name: form.name.trim(),
        model_type: form.model_type,
        provider: form.provider,
        base_url: form.base_url.trim().replace(/\/+$/, ""),
        model_name: form.model_name.trim(),
        api_key: form.api_key === "" ? null : form.api_key,
        enabled: form.enabled,
        expected_revision: revision,
      };
      if (dialog.mode === "create") {
        await adminCreateModel(payload);
        setNotice({ severity: "success", text: "已添加模型。" });
      } else {
        await adminUpdateModel(dialog.row.id, payload);
        setNotice({ severity: "success", text: "已保存模型。" });
      }
      setDialog(null);
      await load();
    } catch (err) {
      if (isConflict(err, "CONFIG_VERSION_CONFLICT")) {
        setNotice({ severity: "error", text: "配置已被其他管理员修改，请刷新后重试。" });
      } else if (isConflict(err, "MODEL_CONFIG_IN_USE")) {
        setNotice({ severity: "error", text: getErrorMessage(err, "该模型正在被服务使用。"), servicesLink: true });
      } else {
        setNotice({ severity: "error", text: getErrorMessage(err, "保存失败。") });
      }
    } finally {
      setSaving(false);
    }
  };

  const toggleEnabled = async (row: LlmModel) => {
    setNotice(null);
    const target = !row.enabled;
    try {
      await adminSetModelEnabled(row.id, target);
      await load();
    } catch (err) {
      if (isConflict(err, "MODEL_CONFIG_IN_USE")) {
        setNotice({ severity: "error", text: getErrorMessage(err, "该模型正在被服务使用。"), servicesLink: true });
      } else if (isConflict(err, "CONFIG_VERSION_CONFLICT")) {
        setNotice({ severity: "error", text: "配置已被其他管理员修改，请刷新后重试。" });
      } else {
        setNotice({ severity: "error", text: getErrorMessage(err, "操作失败。") });
      }
    }
  };

  const testConnection = async (row: LlmModel) => {
    setTestingId(row.id);
    setNotice(null);
    try {
      const result = await adminTestModel({
        model_type: row.model_type,
        provider: row.provider,
        base_url: row.base_url,
        model_name: row.model_name,
        api_key: null,
        model_id: row.id,
      });
      setNotice({ severity: result.ok ? "success" : "error", text: result.message });
    } catch (err) {
      setNotice({ severity: "error", text: getErrorMessage(err, "测试连接失败。") });
    } finally {
      setTestingId(null);
    }
  };

  return (
    <Stack spacing={2}>
      <Box sx={{ display: "flex", justifyContent: "flex-end" }}>
        <Button variant="contained" onClick={openCreate}>添加模型</Button>
      </Box>
      {notice && (
        <Alert severity={notice.severity} onClose={() => setNotice(null)}>
          {notice.text}
          {notice.servicesLink && (
            <Button size="small" color="inherit" sx={{ ml: 1 }} onClick={onGoToServices}>前往服务配置</Button>
          )}
        </Alert>
      )}
      {error ? (
        <ErrorAlert error={error} onRetry={() => void load()} title="加载失败" />
      ) : loading ? (
        <LoadingState label="正在加载模型配置…" />
      ) : models.length === 0 ? (
        <EmptyState
          title="暂无模型配置"
          description="添加模型后，可在“服务配置”中将它用于具体业务。"
        />
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>名称</TableCell>
              <TableCell>类型</TableCell>
              <TableCell>Model</TableCell>
              <TableCell>服务商</TableCell>
              <TableCell>状态</TableCell>
              <TableCell align="right">操作</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {models.map((row) => (
              <TableRow key={row.id}>
                <TableCell>{row.name}</TableCell>
                <TableCell>{TYPE_LABEL[row.model_type]}</TableCell>
                <TableCell>{row.model_name}</TableCell>
                <TableCell>{row.provider}</TableCell>
                <TableCell>
                  <Chip size="small" label={row.enabled ? "已启用" : "已停用"} color={row.enabled ? "success" : "default"} variant="outlined" />
                </TableCell>
                <TableCell align="right">
                  <Button size="small" disabled={testingId === row.id} onClick={() => void testConnection(row)}>
                    {testingId === row.id ? "测试中…" : "测试连接"}
                  </Button>
                  <Button size="small" onClick={() => openEdit(row)}>编辑</Button>
                  <Button size="small" color={row.enabled ? "error" : "primary"} disabled={row.enabled && row.used_by.length > 0} onClick={() => void toggleEnabled(row)}>
                    {row.enabled ? "停用" : "启用"}
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <Dialog open={dialog !== null} onClose={() => setDialog(null)} fullWidth maxWidth="sm">
        <DialogTitle>{dialog?.mode === "create" ? "添加模型" : "编辑模型"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <TextField size="small" label="配置名称" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <FormControl size="small">
              <InputLabel>模型类型</InputLabel>
              <Select
                label="模型类型"
                value={form.model_type}
                disabled={dialog?.mode === "edit" && (dialog as { mode: "edit"; row: LlmModel }).row.used_by.length > 0}
                onChange={(e) => setForm({ ...form, model_type: e.target.value as LlmModelType })}
              >
                <MenuItem value="CHAT">Chat</MenuItem>
                <MenuItem value="EMBEDDING">Embedding</MenuItem>
                <MenuItem value="RERANK">Rerank</MenuItem>
              </Select>
            </FormControl>
            {dialog?.mode === "edit" && (dialog as { mode: "edit"; row: LlmModel }).row.used_by.length > 0 && (
              <Typography variant="caption" color="text.secondary">
                该模型正在被服务使用，暂不能修改类型。
              </Typography>
            )}
            <TextField size="small" label="服务商" value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })} />
            <TextField size="small" label="Base URL" placeholder="https://llm.example.com/v1" value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} />
            <TextField size="small" label="Model 名称" placeholder="Qwen3-32B" value={form.model_name} onChange={(e) => setForm({ ...form, model_name: e.target.value })} />
            <TextField
              size="small"
              label={hasKey ? "API Key（留空保持不变）" : "API Key"}
              type="password"
              placeholder={hasKey ? "••••••••" : "输入 API Key"}
              value={form.api_key}
              onChange={(e) => setForm({ ...form, api_key: e.target.value })}
              helperText="API Key 仅加密保存，接口不返回明文。"
            />
            <FormControlLabel
              control={<Switch checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />}
              label="启用模型"
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialog(null)}>取消</Button>
          <Button variant="contained" disabled={saving || !form.name || !form.base_url || !form.model_name} onClick={() => void submit()}>
            {saving ? "保存中…" : "保存"}
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}

// ---- Tab 二：服务配置 ----

function ServicesTab() {
  const [data, setData] = useState<ServiceBindings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [selected, setSelected] = useState<Record<ServiceType, string>>({} as Record<ServiceType, string>);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [embedConfirm, setEmbedConfirm] = useState(false);
  const originalEmbeddingRef = useRef<string | null>(null);

  const fromServices = (services: ServiceBindings["services"]) => {
    const map = {} as Record<ServiceType, string>;
    for (const s of services) {
      map[s.service_type] = s.model?.id ?? "";
    }
    return map;
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getServiceBindings();
      setData(res);
      setSelected(fromServices(res.services));
      originalEmbeddingRef.current =
        res.services.find((s) => s.service_type === "DOCUMENT_EMBEDDING")?.model?.id ?? null;
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const selectService = (st: ServiceType, value: string) => {
    setSelected((current) => ({ ...current, [st]: value }));
    setDirty(true);
  };

  const buildBindings = (): Record<ServiceType, string | null> => {
    const bindings = {} as Record<ServiceType, string | null>;
    for (const st of ALL_SERVICE_TYPES) {
      bindings[st] = selected[st] ? selected[st] : null;
    }
    return bindings;
  };

  const doSave = async (bindings: Record<ServiceType, string | null>) => {
    setSaving(true);
    setNotice(null);
    try {
      const res = await saveServiceBindings({
        expected_revision: data?.revision ?? null,
        bindings,
      });
      setData(res);
      setSelected(fromServices(res.services));
      originalEmbeddingRef.current =
        res.services.find((s) => s.service_type === "DOCUMENT_EMBEDDING")?.model?.id ?? null;
      setDirty(false);
      setNotice({ severity: "success", text: "服务配置已保存。" });
    } catch (err) {
      setNotice({
        severity: "error",
        text: isConflict(err, "CONFIG_VERSION_CONFLICT")
          ? "配置已被其他管理员修改，请刷新后重试。"
          : getErrorMessage(err, "保存失败。"),
      });
    } finally {
      setSaving(false);
    }
  };

  const handleSave = () => {
    const bindings = buildBindings();
    // Embedding 变更确认（DD-20 §7.3）：从已有模型切换到另一模型
    const newEmbedding = bindings.DOCUMENT_EMBEDDING;
    const oldEmbedding = originalEmbeddingRef.current;
    if (oldEmbedding && newEmbedding && oldEmbedding !== newEmbedding) {
      setEmbedConfirm(true);
      return;
    }
    void doSave(bindings);
  };

  const candidates = (st: ServiceType) =>
    data?.models.filter((m) => m.enabled && m.model_type === SERVICE_MODEL_TYPE[st]) ?? [];

  // 离开页面或刷新时，存在未保存修改则确认（DD-20 §7.4）
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      dirty && currentLocation.pathname !== nextLocation.pathname,
  );

  useEffect(() => {
    if (!dirty) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  const cancelLeave = () => {
    if (blocker.state === "blocked") blocker.reset();
  };
  const confirmLeave = () => {
    if (blocker.state === "blocked") blocker.proceed();
  };

  return (
    <Stack spacing={2}>
      {notice && <Alert severity={notice.severity} onClose={() => setNotice(null)}>{notice.text}</Alert>}
      {error ? (
        <ErrorAlert error={error} onRetry={() => void load()} title="加载失败" />
      ) : loading ? (
        <LoadingState label="正在加载服务配置…" />
      ) : data ? (
        <Stack spacing={3} maxWidth={680}>
          {data.services.map((s) => (
            <Box key={s.service_type}>
              <Typography variant="subtitle1" fontWeight={600}>{s.display_name}</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>{s.description}</Typography>
              <FormControl size="small" fullWidth>
                <InputLabel>使用模型</InputLabel>
                <Select
                  label="使用模型"
                  value={selected[s.service_type] ?? ""}
                  onChange={(e) => selectService(s.service_type, e.target.value as string)}
                >
                  <MenuItem value="">暂不启用</MenuItem>
                  {candidates(s.service_type).map((m) => (
                    <MenuItem key={m.id} value={m.id}>
                      {m.name} / {m.model_name}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Box>
          ))}
          <Box>
            <Button variant="contained" onClick={handleSave} disabled={saving}>
              {saving ? "保存中…" : "保存配置"}
            </Button>
          </Box>
        </Stack>
      ) : null}

      {/* Embedding 变更确认 */}
      <Dialog open={embedConfirm} onClose={() => setEmbedConfirm(false)} fullWidth maxWidth="sm">
        <DialogTitle>更换 Embedding 模型</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            更换 Embedding 模型后，现有向量索引不能直接复用，需要创建新的索引 generation
            并重新向量化。是否继续保存？
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEmbedConfirm(false)}>取消</Button>
          <Button variant="contained" onClick={() => { setEmbedConfirm(false); void doSave(buildBindings()); }}>
            继续保存
          </Button>
        </DialogActions>
      </Dialog>

      {/* 离开确认 */}
      <Dialog open={blocker.state === "blocked"} onClose={cancelLeave} fullWidth maxWidth="xs">
        <DialogTitle>存在未保存修改</DialogTitle>
        <DialogContent>
          <Typography variant="body2">服务配置有未保存的修改，确定要离开当前页面吗？</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={cancelLeave}>留在本页</Button>
          <Button variant="contained" onClick={confirmLeave}>放弃修改并离开</Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}

/** LLM 配置页：模型管理 + 服务配置两个 Tab（DD-20 §5-§7）。 */
export function LlmConfigPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialTab = searchParams.get("tab") === "services" ? 1 : 0;
  const [tab, setTab] = useState(initialTab);

  const handleTabChange = (_event: React.SyntheticEvent, value: number) => {
    setTab(value);
    const next = value === 1 ? "services" : "models";
    setSearchParams(next === "models" ? {} : { tab: next }, { replace: true });
  };

  return (
    <>
      <PageHeader title="LLM 配置" description="管理模型连接，并为各项 AI 服务选择使用的模型。" />
      <Card>
        <CardContent sx={{ p: { xs: 1, sm: 2 } }}>
          <Tabs value={tab} onChange={handleTabChange}>
            <Tab label="模型管理" />
            <Tab label="服务配置" />
          </Tabs>
          <Box sx={{ pt: 2 }}>
            {tab === 0 ? (
              <ModelsTab onGoToServices={() => handleTabChange({} as React.SyntheticEvent, 1)} />
            ) : (
              <ServicesTab />
            )}
          </Box>
        </CardContent>
      </Card>
    </>
  );
}
