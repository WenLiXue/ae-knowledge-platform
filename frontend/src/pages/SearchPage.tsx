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
  TextField,
  Typography,
} from "@mui/material";
import SearchIcon from "@mui/icons-material/Search";
import AddIcon from "@mui/icons-material/Add";
import HistoryIcon from "@mui/icons-material/History";
import {
  CATALOG_OPTIONS,
  appendAssistantMessage,
  buildFollowUpAnswer,
  createConversation,
  createMessage,
  listConversations,
} from "../api/conversations";
import { ErrorAlert } from "../components/ErrorAlert";
import { EmptyState } from "../components/EmptyState";
import { LoadingState } from "../components/LoadingState";
import { PageHeader } from "../components/PageHeader";
import type { Conversation, QueryFilters } from "../types/conversations";

function formatTime(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
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

/** 知识查询页：自然语言提问 + 查询条件 + 最近会话。 */
export function SearchPage() {
  const navigate = useNavigate();

  const [question, setQuestion] = useState("");
  const [productId, setProductId] = useState("");
  const [versionId, setVersionId] = useState("");
  const [documentTypeId, setDocumentTypeId] = useState("");

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const loadConversations = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await listConversations();
      setConversations(result.items);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadConversations();
  }, [loadConversations]);

  const availableVersions = useMemo(
    () => (productId ? (CATALOG_OPTIONS.versions[productId] ?? []) : []),
    [productId],
  );

  const buildFilters = (): QueryFilters => ({
    product_id: productId || null,
    product_version_id: versionId || null,
    document_type_id: documentTypeId || null,
  });

  const handleSubmit = async () => {
    const content = question.trim();
    if (!content || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const filters = buildFilters();
      // MOCK: createConversation / createMessage 当前为 Mock 实现。
      const conversation = await createConversation({ filters });
      await createMessage(conversation.id, content, filters);
      // MOCK: 首问即生成一条演示回答，保证进入会话后即可看到问答内容与低依据提示。
      appendAssistantMessage(conversation.id, buildFollowUpAnswer(content));
      navigate(`/conversations/${conversation.id}`);
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  };

  const handleNewSession = () => {
    setQuestion("");
    setProductId("");
    setVersionId("");
    setDocumentTypeId("");
  };

  return (
    <>
      <PageHeader
        title="知识查询"
        description="用自然语言描述问题，系统将检索已入库知识并给出带来源的答案。"
      />

      {error && <ErrorAlert error={error} onRetry={() => void loadConversations()} title="加载失败" />}

      <Card sx={{ mb: 4 }}>
        <CardContent sx={{ p: { xs: 2, sm: 3 } }}>
          <Stack spacing={2}>
            <TextField
              label="你的问题"
              placeholder="例如：T90000 的 CPU、内存和磁盘配置是什么？"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              multiline
              minRows={3}
              maxRows={6}
              fullWidth
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                  void handleSubmit();
                }
              }}
            />

            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <FormControl size="small" fullWidth>
                <InputLabel>产品</InputLabel>
                <Select
                  label="产品"
                  value={productId}
                  onChange={(event) => {
                    setProductId(event.target.value as string);
                    setVersionId("");
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
                <InputLabel>版本</InputLabel>
                <Select
                  label="版本"
                  value={versionId}
                  onChange={(event) => setVersionId(event.target.value as string)}
                  disabled={!productId}
                >
                  <MenuItem value="">{productId ? "全部版本" : "请先选择产品"}</MenuItem>
                  {availableVersions.map((version) => (
                    <MenuItem key={version.id} value={version.id}>
                      {version.name}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <FormControl size="small" fullWidth>
                <InputLabel>文档类型</InputLabel>
                <Select
                  label="文档类型"
                  value={documentTypeId}
                  onChange={(event) => setDocumentTypeId(event.target.value as string)}
                >
                  <MenuItem value="">全部文档类型</MenuItem>
                  {CATALOG_OPTIONS.documentTypes.map((type) => (
                    <MenuItem key={type.id} value={type.id}>
                      {type.name}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Stack>

            <Stack
              direction={{ xs: "column", sm: "row" }}
              spacing={1.5}
              justifyContent="space-between"
              alignItems={{ xs: "stretch", sm: "center" }}
            >
              <Typography variant="body2" color="text.secondary">
                查询条件用于缩小检索范围，不选则查询全部知识；多轮追问直接在对话中继续提问。
              </Typography>
              <Stack direction="row" spacing={1}>
                <Button variant="outlined" startIcon={<AddIcon />} onClick={handleNewSession}>
                  新建会话
                </Button>
                <Button
                  variant="contained"
                  startIcon={<SearchIcon />}
                  onClick={() => void handleSubmit()}
                  disabled={!question.trim() || submitting}
                >
                  {submitting ? "查询中…" : "查询"}
                </Button>
              </Stack>
            </Stack>
          </Stack>
        </CardContent>
      </Card>

      <Box>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }}>
          <HistoryIcon color="disabled" fontSize="small" />
          <Typography variant="h6">最近会话</Typography>
        </Stack>

        {loading ? (
          <LoadingState label="正在加载最近会话…" />
        ) : conversations.length === 0 ? (
          <Card>
            <EmptyState
              title="还没有会话"
              description="在上方输入问题并点击查询，或直接开始一个新的会话。"
            />
          </Card>
        ) : (
          <Stack spacing={1}>
            {conversations.map((conversation) => (
              <Card
                key={conversation.id}
                sx={{ "&:hover": { borderColor: "primary.main", cursor: "pointer" } }}
                onClick={() => navigate(`/conversations/${conversation.id}`)}
              >
                <CardContent
                  sx={{ p: { xs: 2, sm: 2.5 }, "&:last-child": { pb: { xs: 2, sm: 2.5 } } }}
                >
                  <Stack
                    direction={{ xs: "column", sm: "row" }}
                    spacing={1}
                    justifyContent="space-between"
                    alignItems={{ xs: "flex-start", sm: "center" }}
                  >
                    <Box minWidth={0}>
                      <Typography fontWeight={600} noWrap>
                        {conversation.title}
                      </Typography>
                      <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ mt: 0.75 }}>
                        {conversation.filters.product_id && (
                          <Chip label={`产品：${productName(conversation.filters.product_id)}`} />
                        )}
                        {conversation.filters.product_version_id && (
                          <Chip label={`版本：${versionName(conversation.filters.product_version_id)}`} />
                        )}
                        {conversation.filters.document_type_id && (
                          <Chip label={`类型：${documentTypeName(conversation.filters.document_type_id)}`} />
                        )}
                      </Stack>
                    </Box>
                    <Typography variant="caption" color="text.secondary" sx={{ flexShrink: 0 }}>
                      {formatTime(conversation.last_message_at)}
                    </Typography>
                  </Stack>
                </CardContent>
              </Card>
            ))}
          </Stack>
        )}
      </Box>
    </>
  );
}
