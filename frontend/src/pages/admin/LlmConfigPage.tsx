import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  FormControlLabel,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import { getLlmConfig, testLlmConfig, updateLlmConfig } from "../../api/catalog";
import { getErrorMessage } from "../../api/client";
import { LoadingState } from "../../components/LoadingState";
import { PageHeader } from "../../components/PageHeader";
import type { LlmConfigSaveInput } from "../../types/config";

type Notice = { severity: "info" | "success" | "error"; text: string };

const DEFAULTS: LlmConfigSaveInput = {
  provider: "openai-compatible",
  base_url: "",
  model: "",
  temperature: 0.2,
  top_p: 1,
  max_tokens: 2048,
  timeout_seconds: 60,
  classification_model: "",
  embedding_model: "",
  enabled: false,
  api_key: null,
};

/** LLM 配置页：服务商、模型、参数、API Key 与测试连接。 */
export function LlmConfigPage() {
  const [form, setForm] = useState<LlmConfigSaveInput>(DEFAULTS);
  const [hasKey, setHasKey] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<Notice | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const cfg = await getLlmConfig();
      const { has_api_key, ...rest } = cfg;
      setHasKey(has_api_key);
      setForm({ ...rest, api_key: null });
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const setField = (key: keyof LlmConfigSaveInput) => (
    event: React.ChangeEvent<HTMLInputElement>,
  ) => setForm((current) => ({ ...current, [key]: event.target.value }));

  const setNumber = (key: "temperature" | "top_p" | "max_tokens" | "timeout_seconds") => (
    event: React.ChangeEvent<HTMLInputElement>,
  ) => setForm((current) => ({ ...current, [key]: Number(event.target.value) }));

  const save = async () => {
    setSaving(true);
    setNotice(null);
    try {
      await updateLlmConfig(form);
      setNotice({ severity: "success", text: "配置已保存。" });
      await load();
    } catch (err) {
      setNotice({ severity: "error", text: getErrorMessage(err, "保存失败，请稍后重试。") });
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    setTesting(true);
    setNotice(null);
    try {
      const result = await testLlmConfig(form);
      setNotice({ severity: result.ok ? "success" : "error", text: result.message });
    } catch (err) {
      setNotice({ severity: "error", text: getErrorMessage(err, "测试连接失败。") });
    } finally {
      setTesting(false);
    }
  };

  return (
    <>
      <PageHeader title="LLM 配置" description="配置大模型服务商、模型与参数；API Key 仅加密保存，不返回明文。" />
      {error && <Alert severity="error" sx={{ mb: 2 }}>{getErrorMessage(error, "加载失败")}</Alert>}
      {notice && <Alert severity={notice.severity} sx={{ mb: 2 }}>{notice.text}</Alert>}
      <Card>
        <CardContent sx={{ p: { xs: 2, sm: 3 } }}>
          {loading ? (
            <LoadingState label="正在加载 LLM 配置…" />
          ) : (
            <Stack spacing={2} maxWidth={720}>
              <Typography variant="h6">服务商与模型</Typography>
              <TextField size="small" label="服务商" value={form.provider} onChange={setField("provider")} />
              <TextField size="small" label="Base URL" placeholder="https://api.example.com/v1" value={form.base_url} onChange={setField("base_url")} />
              <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                <TextField size="small" label="对话模型" fullWidth value={form.model} onChange={setField("model")} />
                <TextField size="small" label="分类模型" fullWidth value={form.classification_model} onChange={setField("classification_model")} />
                <TextField size="small" label="Embedding 模型" fullWidth value={form.embedding_model} onChange={setField("embedding_model")} />
              </Stack>
              <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                <TextField size="small" label="温度" type="number" inputProps={{ step: 0.1 }} value={form.temperature} onChange={setNumber("temperature")} />
                <TextField size="small" label="Top P" type="number" inputProps={{ step: 0.1 }} value={form.top_p} onChange={setNumber("top_p")} />
                <TextField size="small" label="最大 Token" type="number" value={form.max_tokens} onChange={setNumber("max_tokens")} />
                <TextField size="small" label="超时（秒）" type="number" value={form.timeout_seconds} onChange={setNumber("timeout_seconds")} />
              </Stack>
              <TextField
                size="small"
                label={hasKey ? "API Key（已配置，留空保持不变）" : "API Key"}
                type="password"
                placeholder={hasKey ? "••••••••" : "输入 API Key"}
                value={form.api_key ?? ""}
                onChange={(event) => setForm((current) => ({ ...current, api_key: event.target.value }))}
                helperText="API Key 仅加密保存，接口不返回明文。"
              />
              <FormControlLabel
                control={<Switch checked={form.enabled} onChange={(event) => setForm((current) => ({ ...current, enabled: event.target.checked }))} />}
                label="启用 LLM"
              />
              <Box>
                <Button variant="contained" onClick={save} disabled={saving || loading} sx={{ mr: 1 }}>
                  {saving ? "保存中…" : "保存配置"}
                </Button>
                <Button variant="outlined" onClick={test} disabled={testing || loading}>
                  {testing ? "测试中…" : "测试连接"}
                </Button>
              </Box>
            </Stack>
          )}
        </CardContent>
      </Card>
    </>
  );
}
