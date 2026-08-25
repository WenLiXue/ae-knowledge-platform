import { useCallback, useEffect, useRef, useState } from "react";
import { Link as RouterLink, useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  IconButton,
  Link,
  LinearProgress,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import SendIcon from "@mui/icons-material/Send";
import ThumbUpOffAltIcon from "@mui/icons-material/ThumbUpOffAlt";
import ThumbDownOffAltIcon from "@mui/icons-material/ThumbDownOffAlt";
import ArticleOutlinedIcon from "@mui/icons-material/ArticleOutlined";
import {
  appendAssistantMessage,
  buildFollowUpAnswer,
  createMessage,
  getConversation,
  getMessages,
  submitFeedback,
} from "../api/conversations";
import { EmptyState } from "../components/EmptyState";
import { ErrorAlert } from "../components/ErrorAlert";
import { FullPageLoading } from "../components/LoadingState";
import type { Answer, AnswerBlock, Citation, Conversation, FeedbackRating, Message } from "../types/conversations";

const FEEDBACK_REASONS = ["答案不准确", "缺少细节", "来源不可信", "未回答问题"];

function formatTime(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatFullTime(value: string): string {
  return new Date(value).toLocaleString("zh-CN", {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function CitationList({ citations }: { citations: Citation[] }) {
  return (
    <Box sx={{ mt: 2 }}>
      <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mb: 1 }}>
        <ArticleOutlinedIcon fontSize="small" color="disabled" />
        <Typography variant="subtitle2">来源引用</Typography>
        <Typography variant="caption" color="text.secondary">
          （{citations.length}）
        </Typography>
      </Stack>
      <Stack spacing={1}>
        {citations.map((citation) => {
          const unavailable = citation.availability !== "AVAILABLE";
          return (
            <Paper key={citation.citation_no} variant="outlined" sx={{ p: 1.5 }}>
              <Stack direction="row" spacing={1.5}>
                <Typography
                  variant="caption"
                  sx={{
                    color: "#0958d9",
                    fontWeight: 700,
                    bgcolor: "#e6f4ff",
                    borderRadius: 1,
                    px: 0.75,
                    py: 0.25,
                    height: "fit-content",
                    flexShrink: 0,
                  }}
                >
                  {citation.citation_no}
                </Typography>
                <Box minWidth={0}>
                  <Typography variant="body2" fontWeight={600}>
                    {citation.document_title}
                  </Typography>
                  <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ mt: 0.5 }}>
                    {citation.document_type && <Chip label={citation.document_type} size="small" />}
                    {citation.version_label && <Chip label={citation.version_label} size="small" variant="outlined" />}
                    <Chip
                      label={`更新：${formatTime(citation.source_updated_at)}`}
                      size="small"
                      variant="outlined"
                    />
                  </Stack>
                  {citation.excerpt && (
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                      {citation.excerpt}
                    </Typography>
                  )}
                  {citation.heading_path.length > 0 && (
                    <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
                      位置：{citation.heading_path.join(" / ")}
                    </Typography>
                  )}
                  <Box sx={{ mt: 0.75 }}>
                    {unavailable ? (
                      <Typography variant="caption" color="warning.main">
                        原文当前不可用
                      </Typography>
                    ) : (
                      <Link
                        href={citation.original_url ?? "#"}
                        target="_blank"
                        rel="noreferrer"
                        underline="hover"
                      >
                        查看原文 →
                      </Link>
                    )}
                  </Box>
                </Box>
              </Stack>
            </Paper>
          );
        })}
      </Stack>
    </Box>
  );
}

function AnswerBlockView({ block }: { block: AnswerBlock }) {
  if (block.type === "paragraph") {
    return (
      // 答案正文对齐原型 .answer-copy：15px / 1.75 行高
      <Typography sx={{ fontSize: 15, lineHeight: 1.75, whiteSpace: "pre-wrap" }}>
        {block.content as string}
      </Typography>
    );
  }
  if (block.type === "table") {
    const table = block.content as { columns: string[]; rows: string[][] };
    return (
      <TableContainer component={Paper} variant="outlined" sx={{ mt: 1 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              {table.columns.map((column) => (
                <TableCell key={column}>
                  {column}
                </TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {table.rows.map((row, rowIndex) => (
              <TableRow key={rowIndex} sx={{ "&:last-child td": { border: 0 } }}>
                {row.map((cell, cellIndex) => (
                  <TableCell key={cellIndex}>{cell}</TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    );
  }
  // list：按换行拆分渲染
  const lines = (block.content as string).split("\n").filter((line) => line.trim());
  return (
    <Stack component="ul" spacing={0.5} sx={{ m: 0, pl: 2.5 }}>
      {lines.map((line, index) => (
        <Typography key={index} component="li" variant="body2">
          {line}
        </Typography>
      ))}
    </Stack>
  );
}

function AnswerView({ answer }: { answer: Answer }) {
  const [panel, setPanel] = useState<FeedbackRating | null>(null);
  const [reasonCodes, setReasonCodes] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const lowEvidence =
    answer.answer_type !== "ANSWER" ||
    answer.degradation_flags.includes("LOW_EVIDENCE") ||
    answer.degradation_flags.includes("NO_EVIDENCE");

  const handleRate = (rating: FeedbackRating) => {
    if (submitted) return;
    setPanel(rating);
    setReasonCodes([]);
  };

  const handleToggleReason = (reason: string) => {
    setReasonCodes((prev) =>
      prev.includes(reason) ? prev.filter((item) => item !== reason) : [...prev, reason],
    );
  };

  const handleSubmitFeedback = async () => {
    if (!panel || submitting) return;
    setSubmitting(true);
    try {
      // MOCK: submitFeedback 当前为 Mock 实现。
      await submitFeedback(answer.id, { rating: panel, reason_codes: reasonCodes });
      setSubmitted(true);
      setPanel(null);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Box>
      {/* 综合答案标题对齐原型 .answer-title */}
      <Typography sx={{ fontSize: 20, fontWeight: 650, lineHeight: 1.4, whiteSpace: "pre-wrap" }}>
        {answer.summary}
      </Typography>

      {answer.blocks.length > 0 && (
        <Stack spacing={1} sx={{ mt: 1.5 }}>
          {answer.blocks.map((block) => (
            <AnswerBlockView key={block.block_id} block={block} />
          ))}
        </Stack>
      )}

      {lowEvidence && (
        <Alert severity="warning" sx={{ mt: 2 }}>
          本次回答依据不足或仅部分命中，请结合下方来源信息核对；也可换个问法或放宽检索条件再试。
        </Alert>
      )}

      {answer.citations.length > 0 && <CitationList citations={answer.citations} />}

      {/* 反馈 */}
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 2 }}>
        {submitted ? (
          <Typography variant="caption" color="success.main">
            已收到你的反馈，感谢！
          </Typography>
        ) : (
          <>
            <Tooltip title="有帮助">
              <IconButton size="small" onClick={() => handleRate("HELPFUL")}>
                <ThumbUpOffAltIcon fontSize="small" />
              </IconButton>
            </Tooltip>
            <Tooltip title="没有帮助">
              <IconButton size="small" onClick={() => handleRate("NOT_HELPFUL")}>
                <ThumbDownOffAltIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </>
        )}
      </Stack>

      {panel && !submitted && (
        <Paper variant="outlined" sx={{ p: 2, mt: 1, bgcolor: "grey.50" }}>
          <Typography variant="body2" fontWeight={600} sx={{ mb: 1 }}>
            {panel === "HELPFUL" ? "有帮助" : "没有帮助"}——如有必要，请补充原因：
          </Typography>
          {panel === "NOT_HELPFUL" && (
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 1.5 }}>
              {FEEDBACK_REASONS.map((reason) => (
                <Chip
                  key={reason}
                  label={reason}
                  size="small"
                  clickable
                  variant={reasonCodes.includes(reason) ? "filled" : "outlined"}
                  color={reasonCodes.includes(reason) ? "primary" : "default"}
                  onClick={() => handleToggleReason(reason)}
                />
              ))}
            </Stack>
          )}
          <Stack direction="row" spacing={1}>
            <Button
              size="small"
              variant="contained"
              disabled={submitting}
              onClick={() => void handleSubmitFeedback()}
            >
              {submitting ? "提交中…" : "提交反馈"}
            </Button>
            <Button size="small" onClick={() => setPanel(null)}>
              取消
            </Button>
          </Stack>
        </Paper>
      )}
    </Box>
  );
}

function MessageRow({ message }: { message: Message }) {
  const isUser = message.role === "user";
  return (
    <Stack direction="row" justifyContent={isUser ? "flex-end" : "flex-start"}>
      {isUser ? (
        <Box
          sx={{
            maxWidth: "72%",
            // 问句气泡对齐原型 .question-bubble：浅蓝底 + 深蓝文字
            bgcolor: "#e6f4ff",
            color: "#17376f",
            borderRadius: "14px 14px 3px 14px",
            px: 2,
            py: 1.25,
          }}
        >
          <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>
            {message.content}
          </Typography>
        </Box>
      ) : (
        <Card sx={{ width: "100%", maxWidth: 880 }}>
          <CardContent>
            {message.answer ? (
              <AnswerView answer={message.answer} />
            ) : (
              <Typography variant="body2" color="text.secondary">
                {message.content || "（答案生成中）"}
              </Typography>
            )}
          </CardContent>
        </Card>
      )}
    </Stack>
  );
}

/** 会话工作台：消息流 + 继续追问 + 流式占位 + 引用与反馈。 */
export function ConversationPage() {
  const { conversationId } = useParams<{ conversationId: string }>();
  const navigate = useNavigate();

  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [streaming, setStreaming] = useState(false);

  const bottomRef = useRef<HTMLDivElement>(null);
  const streamTimerRef = useRef<number | null>(null);

  const load = useCallback(async () => {
    if (!conversationId) return;
    setLoading(true);
    setError(null);
    try {
      const [conv, msgs] = await Promise.all([getConversation(conversationId), getMessages(conversationId)]);
      setConversation(conv);
      setMessages(msgs.items);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [conversationId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    return () => {
      if (streamTimerRef.current) {
        window.clearTimeout(streamTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming]);

  const handleSend = async () => {
    const content = input.trim();
    if (!conversationId || !content || sending || streaming) return;
    setSending(true);
    setError(null);
    try {
      // MOCK: createMessage 当前仅写入 Mock 数据；随后以“流式占位”模拟生成过程。
      await createMessage(conversationId, content);
      const msgs = await getMessages(conversationId);
      setMessages(msgs.items);
      setInput("");
      setStreaming(true);

      streamTimerRef.current = window.setTimeout(() => {
        const answer = buildFollowUpAnswer(content);
        appendAssistantMessage(conversationId, answer);
        void getMessages(conversationId).then((next) => {
          setMessages(next.items);
          setStreaming(false);
        });
      }, 1200);
    } catch (err) {
      setError(err);
    } finally {
      setSending(false);
    }
  };

  if (loading) {
    return <FullPageLoading />;
  }

  if (error && !conversation) {
    return <ErrorAlert error={error} onRetry={() => void load()} title="加载失败" />;
  }

  if (!conversation) {
    return null;
  }

  // 查询工作区不再由外层 Container 提供宽度，页面自身补充等价约束。
  return (
    <Box sx={{ width: "100%", maxWidth: 880, mx: "auto", p: { xs: 2, sm: 3 } }}>
      <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 2 }}>
        <IconButton component={RouterLink} to="/search" aria-label="返回知识查询">
          <ArrowBackIcon />
        </IconButton>
        <Box minWidth={0}>
          <Typography variant="h6" noWrap>
            {conversation.title}
          </Typography>
          <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
            {conversation.filters.product_id && <Chip label={`产品：${conversation.filters.product_id}`} size="small" />}
            {conversation.filters.product_version_id && (
              <Chip label={`版本：${conversation.filters.product_version_id}`} size="small" />
            )}
            {conversation.filters.document_type_id && (
              <Chip label={`类型：${conversation.filters.document_type_id}`} size="small" />
            )}
          </Stack>
        </Box>
      </Stack>

      {error ? <ErrorAlert error={error} onRetry={() => void load()} title="操作失败" /> : null}

      <Card sx={{ display: "flex", flexDirection: "column", minHeight: { xs: "60vh", md: "70vh" } }}>
        <CardContent
          sx={{
            flexGrow: 1,
            overflowY: "auto",
            display: "flex",
            flexDirection: "column",
            gap: 2,
            maxHeight: { md: 560 },
            p: { xs: 2, sm: 2.5 },
            "&:last-child": { pb: { xs: 2, sm: 2.5 } },
          }}
        >
          {messages.length === 0 ? (
            <Box sx={{ py: 6 }}>
              <EmptyState
                title="开始提问"
                description="在下方输入你的问题，系统将检索已入库知识并给出带来源的答案。"
              />
            </Box>
          ) : (
            messages.map((message) => <MessageRow key={message.id} message={message} />)
          )}

          {streaming && (
            <Stack direction="row" justifyContent="flex-start">
              <Card sx={{ width: "100%", maxWidth: 880 }}>
                <CardContent>
                  <Typography variant="body2" sx={{ mb: 1 }}>
                    正在检索知识库并生成答案…
                  </Typography>
                  <LinearProgress />
                </CardContent>
              </Card>
            </Stack>
          )}

          <div ref={bottomRef} />
        </CardContent>

        <Box sx={{ p: 2, borderTop: 1, borderColor: "divider", bgcolor: "grey.50" }}>
          <Stack direction="row" spacing={1.5} alignItems="flex-end">
            <TextField
              label="继续追问"
              placeholder="输入你的问题，Enter 发送，Shift+Enter 换行"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              multiline
              minRows={1}
              maxRows={4}
              fullWidth
              size="small"
              disabled={streaming}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void handleSend();
                }
              }}
            />
            <Tooltip title="发送">
              <span>
                <IconButton
                  color="primary"
                  onClick={() => void handleSend()}
                  disabled={!input.trim() || sending || streaming}
                  sx={{ border: 1, borderColor: "divider", bgcolor: "background.paper" }}
                >
                  {sending ? <CircularProgress size={20} /> : <SendIcon />}
                </IconButton>
              </span>
            </Tooltip>
          </Stack>
          <Stack direction="row" justifyContent="space-between" sx={{ mt: 1 }}>
            <Typography variant="caption" color="text.secondary">
              回答将优先给出答案，并附上引用来源供核对。
            </Typography>
            <Typography variant="caption" color="text.secondary">
              最后更新：{formatFullTime(conversation.last_message_at ?? conversation.created_at)}
            </Typography>
          </Stack>
        </Box>
      </Card>
    </Box>
  );
}
