import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Container,
  Divider,
  List,
  ListItem,
  ListItemText,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";

type FeishuDocument = {
  resource_token: string;
  title: string;
  resource_type: "wiki" | "docx";
  modified_at: string;
  owner_name: string;
  submitted: boolean;
  source_id: string | null;
};

type KnowledgeSource = {
  source_id: string;
  resource_token: string | null;
  resource_type: string | null;
  display_name: string;
  status: string;
  update_status: string;
  version_id: string | null;
  version_status: string | null;
  task_id: string | null;
  task_status: string | null;
  created_at: string | null;
};

type SubmitItemResult = {
  client_item_id: string;
  resource_token: string;
  source_id: string;
  version_id: string | null;
  task_id: string | null;
  status: string;
  duplicate: boolean;
};

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

const SOURCE_STATUS_LABEL: Record<string, { label: string; color: "default" | "info" | "warning" | "success" | "error" }> = {
  PROCESSING: { label: "处理中", color: "info" },
  PENDING_CONFIRMATION: { label: "待确认", color: "warning" },
  QUERYABLE: { label: "可查询", color: "success" },
  FAILED: { label: "失败", color: "error" },
  OFFLINE: { label: "已下线", color: "default" },
};

function statusChip(status: string | null) {
  const meta = SOURCE_STATUS_LABEL[status ?? ""] ?? { label: status ?? "未知", color: "default" as const };
  return <Chip size="small" label={meta.label} color={meta.color} variant="outlined" />;
}

export default function App() {
  const [documents, setDocuments] = useState<FeishuDocument[]>([]);
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<{ severity: "info" | "success" | "error"; text: string } | null>(null);

  const loadSources = useCallback(async () => {
    const response = await fetch(`${API_BASE_URL}/api/v1/knowledge-sources`);
    if (!response.ok) throw new Error("来源列表加载失败");
    const payload = await response.json();
    setSources(payload.data.items as KnowledgeSource[]);
  }, []);

  const refreshSources = async () => {
    try {
      await loadSources();
      setMessage({ severity: "success", text: "来源状态已刷新。" });
    } catch (error) {
      setMessage({
        severity: "error",
        text: error instanceof Error ? error.message : "来源状态刷新失败",
      });
    }
  };

  useEffect(() => {
    const loadDocuments = async () => {
      try {
        const docResponse = await fetch(`${API_BASE_URL}/api/v1/feishu/documents`);
        if (!docResponse.ok) throw new Error("文档列表加载失败");
        const payload = await docResponse.json();
        setDocuments(payload.data.items as FeishuDocument[]);
        await loadSources();
      } catch (error) {
        setMessage({
          severity: "error",
          text: error instanceof Error ? error.message : "文档列表加载失败",
        });
      } finally {
        setLoading(false);
      }
    };

    void loadDocuments();
  }, [loadSources]);

  const visibleDocuments = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return documents;
    return documents.filter((document) => document.title.toLowerCase().includes(keyword));
  }, [documents, query]);

  const toggleSelection = (token: string) => {
    setSelected((current) =>
      current.includes(token) ? current.filter((item) => item !== token) : [...current, token],
    );
  };

  const submitSelected = async () => {
    setSubmitting(true);
    setMessage(null);
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/feishu/documents/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          items: selected.map((token) => {
            const document = documents.find((item) => item.resource_token === token)!;
            return {
              client_item_id: token,
              resource_token: token,
              resource_type: document.resource_type,
            };
          }),
        }),
      });
      if (!response.ok) throw new Error("文档提交失败");
      const payload = await response.json();
      const results = payload.data.items as SubmitItemResult[];
      const created = results.filter((item) => !item.duplicate);
      const duplicated = results.filter((item) => item.duplicate);

      setDocuments((current) =>
        current.map((document) =>
          selected.includes(document.resource_token) ? { ...document, submitted: true } : document,
        ),
      );
      setSelected([]);

      let text = `已提交入库 ${created.length} 个文档，正在处理中。`;
      if (duplicated.length > 0) {
        text += ` 其中 ${duplicated.length} 个已存在，未重复入库。`;
      }
      setMessage({
        severity: duplicated.length > 0 && created.length === 0 ? "info" : "success",
        text,
      });

      await loadSources();
    } catch (error) {
      setMessage({
        severity: "error",
        text: error instanceof Error ? error.message : "文档提交失败",
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Container maxWidth="lg" sx={{ py: 8 }}>
      <Stack spacing={3}>
        <Box>
          <Typography color="primary" variant="overline">
            AE Knowledge Platform
          </Typography>
          <Typography variant="h3" component="h1" sx={{ mt: 1, fontWeight: 700 }}>
            产品知识智能平台
          </Typography>
          <Typography color="text.secondary" sx={{ mt: 1 }}>
            发现并导入飞书文档，处理状态已持久化到数据库。
          </Typography>
        </Box>
        {message && <Alert severity={message.severity}>{message.text}</Alert>}
        <Paper variant="outlined" sx={{ p: 3 }}>
          <Stack spacing={2}>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2} justifyContent="space-between">
              <Box>
                <Typography variant="h6">选择飞书文档</Typography>
                <Typography color="text.secondary" variant="body2" sx={{ mt: 0.5 }}>
                  只展示当前用户可见的文档元数据，提交后才会读取正文并进入处理流程。
                </Typography>
              </Box>
              <Button variant="contained" disabled={!selected.length || submitting} onClick={submitSelected}>
                {submitting ? "提交中…" : `提交入库${selected.length ? `（${selected.length}）` : ""}`}
              </Button>
            </Stack>
            <TextField
              size="small"
              label="搜索文档标题"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              fullWidth
            />
            <Divider />
            {loading ? (
              <Typography color="text.secondary">正在加载飞书文档…</Typography>
            ) : (
              <List disablePadding>
                {visibleDocuments.map((document) => (
                  <ListItem key={document.resource_token} disableGutters divider>
                    <Checkbox
                      checked={selected.includes(document.resource_token)}
                      disabled={document.submitted}
                      onChange={() => toggleSelection(document.resource_token)}
                    />
                    <ListItemText
                      primary={document.title}
                      secondary={`${document.owner_name} · 最近修改 ${new Date(document.modified_at).toLocaleDateString("zh-CN")}`}
                    />
                    <Chip
                      size="small"
                      label={document.submitted ? "已提交" : document.resource_type.toUpperCase()}
                      color={document.submitted ? "success" : "default"}
                      variant={document.submitted ? "filled" : "outlined"}
                    />
                  </ListItem>
                ))}
              </List>
            )}
          </Stack>
        </Paper>

        <Paper variant="outlined" sx={{ p: 3 }}>
          <Stack spacing={2}>
            <Stack direction="row" spacing={2} justifyContent="space-between" alignItems="flex-start">
              <Box>
                <Typography variant="h6">已入库来源</Typography>
                <Typography color="text.secondary" variant="body2" sx={{ mt: 0.5 }}>
                  状态来自数据库；启动 Worker（python -m app.worker）后，来源会推进到“可查询”。
                </Typography>
              </Box>
              <Button size="small" variant="outlined" onClick={refreshSources}>
                刷新
              </Button>
            </Stack>
            {sources.length === 0 ? (
              <Typography color="text.secondary">暂无已提交的来源。</Typography>
            ) : (
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>文档</TableCell>
                    <TableCell>来源状态</TableCell>
                    <TableCell>版本状态</TableCell>
                    <TableCell>任务状态</TableCell>
                    <TableCell>提交时间</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {sources.map((source) => (
                    <TableRow key={source.source_id}>
                      <TableCell>{source.display_name}</TableCell>
                      <TableCell>{statusChip(source.status)}</TableCell>
                      <TableCell>{statusChip(source.version_status)}</TableCell>
                      <TableCell>{statusChip(source.task_status)}</TableCell>
                      <TableCell>
                        {source.created_at ? new Date(source.created_at).toLocaleString("zh-CN") : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </Stack>
        </Paper>
      </Stack>
    </Container>
  );
}
