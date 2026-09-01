import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Box, Stack, Typography, useMediaQuery, type Theme } from "@mui/material";
import { createConversation, createMessage } from "../api/conversations";
import { ErrorAlert } from "../components/ErrorAlert";
import { QueryComposer } from "../components/query/QueryComposer";
import { useConversationWorkspace } from "../conversations/ConversationWorkspaceContext";
import type { QueryFilters } from "../types/conversations";

const EMPTY_FILTERS: QueryFilters = {
  product_id: null,
  product_version_id: null,
  document_type_id: null,
};

/** 知识查询首页：Codex 式工作区 —— 居中 Composer + 可选范围 + 示例问题。 */
export function SearchPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { refreshConversations } = useConversationWorkspace();
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null);

  const [question, setQuestion] = useState("");
  const [filters, setFilters] = useState<QueryFilters>(EMPTY_FILTERS);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const isDesktop = useMediaQuery((theme: Theme) => theme.breakpoints.up("md"));

  // 侧栏“新建查询”在已处于 /search 时会 push 一个新的 location.key，
  // 借此清空表单，避免强制刷新整个浏览器。
  useEffect(() => {
    setQuestion("");
    setFilters(EMPTY_FILTERS);
    setError(null);
  }, [location.key]);

  const handleSubmit = async () => {
    const content = question.trim();
    if (!content || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const conversation = await createConversation({ filters });
      await createMessage(conversation.id, content, filters);
      // 新会话进入侧栏列表。
      void refreshConversations();
      navigate(`/conversations/${conversation.id}`);
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Box sx={{ flexGrow: 1, minHeight: 0, minWidth: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {/* 顶部轻量工具栏：移动端由 AppBar 承担，避免双顶栏 */}
      <Stack
        direction="row"
        alignItems="center"
        sx={{ display: { xs: "none", md: "flex" }, minHeight: 58, px: 3, flexShrink: 0 }}
      >
        <Typography variant="subtitle1" fontWeight={600}>
          智能问答
        </Typography>
      </Stack>

      {/* 欢迎区：桌面垂直居中，移动端从顶部自然排列 */}
      <Box
        sx={{
          flexGrow: 1,
          minHeight: 0,
          display: "flex",
          flexDirection: "column",
          px: { xs: 2, sm: 3 },
        }}
      >
        <Box
          sx={{
            width: "100%",
            maxWidth: 760,
            mx: "auto",
            my: { xs: 0, md: "auto" },
            py: { xs: 5, md: 6 },
          }}
        >
          <Box sx={{ textAlign: { xs: "left", md: "center" }, mb: 3 }}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              基于已入库的产品资料回答
            </Typography>
            <Typography
              component="h1"
              sx={{
                fontSize: { xs: 26, sm: 32, md: 38 },
                fontWeight: 620,
                lineHeight: 1.25,
                letterSpacing: "-0.035em",
              }}
            >
              今天想查询什么？
            </Typography>
          </Box>

          {error ? <ErrorAlert error={error} onRetry={() => void handleSubmit()} title="查询失败" /> : null}

          <QueryComposer
            question={question}
            filters={filters}
            submitting={submitting}
            onQuestionChange={setQuestion}
            onFiltersChange={setFilters}
            onSubmit={() => void handleSubmit()}
            autoFocus={isDesktop}
            inputRef={inputRef}
          />

          <Typography
            variant="caption"
            color="text.disabled"
            sx={{ mt: 1.5, display: "block", textAlign: { xs: "left", md: "center" } }}
          >
            Enter 换行，Ctrl + Enter 查询
          </Typography>
        </Box>
      </Box>

      {/* 底部事实核验提示 */}
      <Typography
        variant="caption"
        color="text.disabled"
        sx={{ flexShrink: 0, textAlign: "center", px: 2, py: 1.5 }}
      >
        答案基于企业知识库生成，请通过引用来源核验关键事实。
      </Typography>
    </Box>
  );
}
