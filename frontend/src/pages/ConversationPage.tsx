import { useCallback, useEffect, useRef, useState } from "react";
import { Link as RouterLink, useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  Link,
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
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import {
  cancelAnswer,
  createMessage,
  getConversation,
  getMessages,
  listAnswerApprovals,
  decideAnswerApproval,
  isInProgress,
  retryAnswer,
  submitFeedback,
  subscribeAnswerEvents,
  type StreamingAnswer,
} from "../api/conversations";
import { useConversationWorkspace } from "../conversations/ConversationWorkspaceContext";
import { EmptyState } from "../components/EmptyState";
import { ErrorAlert } from "../components/ErrorAlert";
import { FullPageLoading } from "../components/LoadingState";
import type { AgentApproval, Answer, AnswerBlock, Citation, Conversation, FeedbackRating, Message } from "../types/conversations";

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

function streamStageText(streaming: StreamingAnswer): string {
  const stage = streaming.progress_stage ?? streaming.status;
  const labels: Record<string, string> = {
    PENDING: "问题已提交，等待处理",
    UNDERSTANDING: "正在理解问题",
    RETRIEVING: "正在检索知识库",
    RERANKING: "正在重排候选资料",
    GENERATING: "正在生成答案",
    VALIDATING: "正在校验引用",
    STREAMING: "正在生成答案",
    SUCCEEDED: "回答完成",
    FAILED: "回答失败",
    CANCELED: "已停止生成",
  };
  return labels[stage] ?? `处理中（${stage}）`;
}

function CitationList({ citations }: { citations: Citation[] }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <Accordion
      expanded={expanded}
      onChange={(_event, nextExpanded) => setExpanded(nextExpanded)}
      disableGutters
      elevation={0}
      sx={{ mt: 2, border: 1, borderColor: "divider", borderRadius: 1, "&:before": { display: "none" } }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ minHeight: 44, px: 1.5, "& .MuiAccordionSummary-content": { my: 1 } }}>
        <Stack direction="row" spacing={0.75} alignItems="center">
          <ArticleOutlinedIcon fontSize="small" color="disabled" />
          <Typography variant="subtitle2">来源文档</Typography>
          <Typography variant="caption" color="text.secondary">
            （{citations.length}）
          </Typography>
        </Stack>
      </AccordionSummary>
      <AccordionDetails sx={{ pt: 0, px: 1.5, pb: 1.5 }}>
        <Stack spacing={1}>
          {citations.map((citation) => {
            const unavailable = citation.availability !== "AVAILABLE";
            const locations = citation.locations?.length
              ? citation.locations
              : [{
                  chunk_id: null,
                  heading_path: citation.heading_path ?? [],
                  locator: {},
                  excerpt: citation.excerpt,
                }];
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
                      {citation.support_count > 1 && (
                        <Chip label={`${citation.support_count} 个相关片段`} size="small" variant="outlined" />
                      )}
                      <Chip
                        label={`更新：${formatTime(citation.source_updated_at)}`}
                        size="small"
                        variant="outlined"
                      />
                    </Stack>
                    <Stack spacing={0.75} sx={{ mt: 0.75 }}>
                      {locations.map((location, index) => (
                        <Box
                          key={location.chunk_id ?? `${citation.citation_no}-${index}`}
                          sx={{
                            pt: index === 0 ? 0 : 0.75,
                            borderTop: index === 0 ? 0 : 1,
                            borderColor: "divider",
                          }}
                        >
                          {locations.length > 1 && (
                            <Typography variant="caption" color="text.secondary" display="block">
                              相关片段 {index + 1}
                            </Typography>
                          )}
                          {location.heading_path.length > 0 && (
                            <Typography variant="caption" color="text.secondary" display="block">
                              位置：{location.heading_path.join(" / ")}
                            </Typography>
                          )}
                          {location.excerpt && (
                            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.25 }}>
                              {location.excerpt}
                            </Typography>
                          )}
                        </Box>
                      ))}
                    </Stack>
                    <Box sx={{ mt: 0.75 }}>
                      {unavailable || !citation.original_url ? (
                        <Typography variant="caption" color="warning.main">
                          {unavailable ? "原文当前不可用" : "暂无可用的原文地址"}
                        </Typography>
                      ) : (
                        <Link
                          href={citation.original_url}
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
      </AccordionDetails>
    </Accordion>
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

function AnswerView({ answer, onRetry }: { answer: Answer; onRetry?: () => void }) {
  const [panel, setPanel] = useState<FeedbackRating | null>(null);
  const [reasonCodes, setReasonCodes] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [approvals, setApprovals] = useState<AgentApproval[]>([]);
  const [approvalBusy, setApprovalBusy] = useState<string | null>(null);

  useEffect(() => {
    if (answer.status !== "WAITING") {
      setApprovals([]);
      return;
    }
    void listAnswerApprovals(answer.id)
      .then((result) => setApprovals(result.items))
      .catch(() => undefined);
  }, [answer.id, answer.status]);

  const decideApproval = async (approval: AgentApproval, decision: "APPROVED" | "REJECTED") => {
    if (approvalBusy) return;
    setApprovalBusy(approval.id);
    try {
      await decideAnswerApproval(answer.id, approval.id, decision);
      const result = await listAnswerApprovals(answer.id);
      setApprovals(result.items);
    } finally {
      setApprovalBusy(null);
    }
  };

  // 仅对已完成的回答判断证据充分性；进行中（answer_type 为 null）不提前提示依据不足
  const lowEvidence =
    answer.status === "SUCCEEDED" &&
    (answer.answer_type !== "ANSWER" ||
      answer.degradation_flags.includes("LOW_EVIDENCE") ||
      answer.degradation_flags.includes("NO_EVIDENCE"));

  // 模型可能同时把完整回答写入 summary 和 blocks；展示时避免重复输出。
  const visibleBlocks = answer.blocks.filter((block, index, all) => {
    const value = typeof block.content === "string" ? block.content : JSON.stringify(block.content);
    return all.findIndex((candidate) => {
      const other = typeof candidate.content === "string" ? candidate.content : JSON.stringify(candidate.content);
      return other.trim() === value.trim();
    }) === index;
  });
  // blocks 是生成答案的正文；summary 仅用于没有正文块的澄清/降级回答。
  // 不尝试用字符串相似度判断，避免模型换一种措辞时仍出现两段重复问候。
  const showSummary = visibleBlocks.length === 0 && Boolean(answer.summary?.trim());

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
      {(answer.status === "FAILED" || showSummary) && (
        <Typography sx={{ fontSize: 20, fontWeight: 650, lineHeight: 1.4, whiteSpace: "pre-wrap" }}>
          {answer.status === "FAILED" ? "回答生成失败，请重试。" : answer.summary}
        </Typography>
      )}

      {answer.status === "FAILED" && (
        <Alert severity="error" sx={{ mt: 1.5 }} action={onRetry ? (
          <Button color="inherit" size="small" onClick={onRetry}>重新生成</Button>
        ) : undefined}>
          网络或服务暂时异常，本次回答未完成。
          {answer.error_code && <Typography variant="caption" display="block" sx={{ mt: 0.5 }}>错误编号：{answer.error_code}</Typography>}
        </Alert>
      )}

      {answer.status === "WAITING" && approvals.filter((item) => item.status === "PENDING").map((approval) => (
        <Alert key={approval.id} severity="warning" sx={{ mt: 1.5 }}>
          <Typography variant="body2" fontWeight={600}>需要确认后执行操作</Typography>
          <Typography variant="body2" sx={{ mt: 0.5 }}>
            {approval.impact_summary.step_title || approval.tool_name}：{approval.impact_summary.summary || "该操作会修改任务状态"}
          </Typography>
          <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
            <Button size="small" variant="contained" disabled={approvalBusy !== null} onClick={() => void decideApproval(approval, "APPROVED")}>确认执行</Button>
            <Button size="small" variant="outlined" color="inherit" disabled={approvalBusy !== null} onClick={() => void decideApproval(approval, "REJECTED")}>拒绝</Button>
          </Stack>
        </Alert>
      ))}

      {visibleBlocks.length > 0 && (
        <Stack spacing={1} sx={{ mt: 1.5 }}>
          {visibleBlocks.map((block) => (
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

function MessageRow({ message, onRetry }: { message: Message; onRetry?: () => void }) {
  const isUser = message.role === "user";
  return (
    <Stack
      direction="row"
      justifyContent={isUser ? "flex-end" : "flex-start"}
      sx={{ px: { xs: 0, sm: 1 } }}
    >
      {isUser ? (
        <Box
          sx={{
            maxWidth: { xs: "88%", sm: "72%" },
            // 问句气泡对齐原型 .question-bubble：浅蓝底 + 深蓝文字
            bgcolor: "#e6f4ff",
            color: "#17376f",
            borderRadius: "16px 16px 4px 16px",
            px: 2,
            py: 1.25,
          }}
        >
          <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>
            {message.content}
          </Typography>
        </Box>
      ) : (
        <Box
          component="article"
          sx={{
            width: "100%",
            maxWidth: 1000,
            py: { xs: 2, sm: 2.5 },
            borderBottom: 1,
            borderColor: "divider",
          }}
        >
          <Typography
            variant="overline"
            sx={{ display: "block", mb: 1, color: "primary.main", letterSpacing: "0.08em" }}
          >
            知识助手
          </Typography>
          {message.answer ? (
            <AnswerView answer={message.answer} onRetry={onRetry} />
          ) : (
            <Typography variant="body2" color="text.secondary">
              {message.content || "（答案生成中）"}
            </Typography>
          )}
        </Box>
      )}
    </Stack>
  );
}

/** 会话工作台：消息流 + 继续追问 + 流式占位 + 引用与反馈。 */
export function ConversationPage() {
  const { conversationId } = useParams<{ conversationId: string }>();
  const navigate = useNavigate();
  const { refreshConversations } = useConversationWorkspace();

  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [streaming, setStreaming] = useState<StreamingAnswer | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);

  /** 拉取消息并检测是否有进行中的回答（刷新/断线后据此恢复 SSE 订阅）。 */
  const refreshMessages = useCallback(async () => {
    if (!conversationId) return;
    const msgs = await getMessages(conversationId);
    setMessages(msgs.items);
    const active = msgs.items.find((m) => m.answer && isInProgress(m.answer.status));
    if (active?.answer) {
      const a = active.answer;
      setStreaming({
        answer_id: a.id,
        status: a.status,
        progress_stage: a.progress_stage ?? null,
        answer_type: a.answer_type,
        summary: a.summary,
        blocks: a.blocks,
        citations: a.citations,
        degradation_flags: a.degradation_flags,
      });
    } else {
      setStreaming(null);
    }
  }, [conversationId]);

  const load = useCallback(async (signal?: AbortSignal) => {
    if (!conversationId) return;
    // 先清空上一会话的进行中状态，避免切换会话时短暂展示旧答案的阶段。
    setStreaming(null);
    setLoading(true);
    setError(null);
    try {
      const [conv, msgs] = await Promise.all([
        getConversation(conversationId, signal),
        getMessages(conversationId, signal),
      ]);
      setConversation(conv);
      setMessages(msgs.items);
      const active = msgs.items.find((m) => m.answer && isInProgress(m.answer.status));
      if (active?.answer) {
        const a = active.answer;
        setStreaming({
          answer_id: a.id,
          status: a.status,
          progress_stage: a.progress_stage ?? null,
          answer_type: a.answer_type,
          summary: a.summary,
          blocks: a.blocks,
          citations: a.citations,
          degradation_flags: a.degradation_flags,
        });
      } else {
        setStreaming(null);
      }
    } catch (err) {
      if (signal?.aborted) return;
      setError(err);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [conversationId]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  // 订阅进行中回答的 SSE：状态变化实时展示，终结后重拉消息流。
  useEffect(() => {
    if (!streaming?.answer_id) return;
    let cancelled = false;
    const close = subscribeAnswerEvents(streaming.answer_id, {
      onSnapshot: (answer) => {
        if (cancelled) return;
        setStreaming({
          answer_id: answer.id,
          status: answer.status,
          progress_stage: answer.progress_stage ?? null,
          answer_type: answer.answer_type,
          summary: answer.summary,
          blocks: answer.blocks,
          citations: answer.citations,
          degradation_flags: answer.degradation_flags,
        });
        if (!isInProgress(answer.status)) {
          close();
          void refreshMessages();
        }
      },
      onStatus: (payload) => {
        if (cancelled) return;
        setStreaming((prev) =>
          prev ? { ...prev, status: payload.status, progress_stage: payload.progress_stage } : prev,
        );
      },
      onBlock: (block) => {
        if (cancelled) return;
        setStreaming((prev) => (prev ? { ...prev, blocks: [...prev.blocks, block] } : prev));
      },
      onCitation: (citation) => {
        if (cancelled) return;
        setStreaming((prev) => (prev ? { ...prev, citations: [...prev.citations, citation] } : prev));
      },
      onDone: () => {
        if (cancelled) return;
        close();
        void refreshMessages();
      },
      onEnd: () => {
        if (!cancelled) void refreshMessages();
      },
    });
    return () => {
      cancelled = true;
      close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [streaming?.answer_id]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming?.status]);

  const handleSend = async () => {
    const content = input.trim();
    if (!conversationId || !content || sending || streaming) return;
    setSending(true);
    setError(null);
    try {
      await createMessage(conversationId, content);
      setInput("");
      await refreshMessages();
    } catch (err) {
      if (err instanceof Error && (err as { code?: string }).code === "ANSWER_ALREADY_IN_PROGRESS") {
        setError(new Error("该会话已有回答正在生成，请稍候。"));
      } else {
        setError(err);
      }
    } finally {
      setSending(false);
    }
  };

  const handleCancel = async () => {
    if (!streaming) return;
    try {
      await cancelAnswer(streaming.answer_id);
    } catch (err) {
      setError(err);
    }
  };

  const handleRetry = async (answerId: string) => {
    if (sending || streaming) return;
    setSending(true);
    setError(null);
    try {
      await retryAnswer(answerId);
      await refreshMessages();
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
    <Box
      sx={{
        width: { xs: "100%", md: "calc(100% - 48px)" },
        maxWidth: 1400,
        height: "100%",
        minHeight: 0,
        ml: { xs: 0, md: "clamp(24px, 4vw, 64px)" },
        mr: { xs: 0, md: "auto" },
        px: { xs: 1.5, sm: 2.5 },
        pt: { xs: 1.5, sm: 2 },
        display: "flex",
        flexDirection: "column",
      }}
    >
      <Stack
        direction="row"
        spacing={1.5}
        alignItems="center"
        sx={{ width: "100%", maxWidth: 1000, mb: 1.5, flexShrink: 0 }}
      >
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
        <Box sx={{ flexGrow: 1 }} />
      </Stack>

      {error ? <ErrorAlert error={error} onRetry={() => void load()} title="操作失败" /> : null}

      <Box
        sx={{
          display: "flex",
          flexDirection: "column",
          flex: 1,
          minHeight: 0,
          overflow: "hidden",
          bgcolor: "background.paper",
          border: 1,
          borderColor: "divider",
          borderRadius: 2,
        }}
      >
        <Box
          sx={{
            flexGrow: 1,
            overflowY: "auto",
            display: "flex",
            flexDirection: "column",
            gap: 2,
            minHeight: 0,
            px: { xs: 2, sm: 3.5 },
            py: { xs: 1, sm: 1.5 },
            scrollbarGutter: "stable",
            alignItems: "flex-start",
            "& > *": { width: "100%", maxWidth: 1000 },
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
            messages.map((message) => (
              <MessageRow
                key={message.id}
                message={message}
                onRetry={message.answer ? () => void handleRetry(message.answer!.id) : undefined}
              />
            ))
          )}

          {streaming && (
            <Paper variant="outlined" sx={{ p: 2, bgcolor: "rgba(255,255,255,0.62)" }}>
              <Stack direction="row" spacing={1.5} alignItems="center">
                <CircularProgress size={18} />
                <Box minWidth={0}>
                  <Typography variant="subtitle2">{streamStageText(streaming)}</Typography>
                  <Typography variant="caption" color="text.secondary">
                    {streaming.degradation_flags.length > 0
                      ? "（降级模式：部分能力暂不可用）"
                      : "检索结果和来源引用会显示在这里。"}
                  </Typography>
                </Box>
                <Box sx={{ flexGrow: 1 }} />
                <Button size="small" color="inherit" onClick={() => void handleCancel()}>
                  停止生成
                </Button>
              </Stack>
            </Paper>
          )}

          {!streaming &&
            messages.length > 0 &&
            !messages.some((message) => message.role === "assistant") && (
              <Box
                sx={{
                  flex: 1,
                  minHeight: 180,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  px: 2,
                }}
              >
                <Paper
                  variant="outlined"
                  sx={{
                    width: "min(100%, 520px)",
                    px: 3,
                    py: 2.5,
                    textAlign: "center",
                    borderStyle: "dashed",
                    bgcolor: "rgba(255,255,255,0.62)",
                  }}
                >
                  <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
                    问题已收到，等待答案生成
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    检索结果和来源引用会显示在这里。
                  </Typography>
                </Paper>
              </Box>
            )}

          <div ref={bottomRef} />
        </Box>

        <Box
          sx={{
            px: { xs: 1.5, sm: 2.5 },
            py: { xs: 1.5, sm: 2 },
            borderTop: 1,
            borderColor: "divider",
            bgcolor: "#f8fafc",
          }}
        >
          <Stack direction="row" spacing={1.5} alignItems="flex-end" sx={{ maxWidth: 1000 }}>
            <TextField
              placeholder="输入你的问题，Enter 发送，Shift+Enter 换行"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              multiline
              minRows={1}
              maxRows={4}
              fullWidth
              disabled={sending || !!streaming}
              inputProps={{ "aria-label": "继续追问" }}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void handleSend();
                }
              }}
            />
            <Tooltip title={streaming ? "回答生成中，请稍候" : "发送"}>
              <span>
                <IconButton
                  color="primary"
                  onClick={() => void handleSend()}
                  disabled={!input.trim() || sending || !!streaming}
                  sx={{
                    width: 44,
                    height: 44,
                    color: "common.white",
                    bgcolor: "primary.main",
                    "&:hover": { bgcolor: "primary.dark" },
                    "&.Mui-disabled": { bgcolor: "grey.200", color: "grey.400" },
                  }}
                >
                  {sending ? <CircularProgress size={20} /> : <SendIcon />}
                </IconButton>
              </span>
            </Tooltip>
          </Stack>
          <Stack
            direction={{ xs: "column", sm: "row" }}
            justifyContent="space-between"
            spacing={0.25}
            sx={{ maxWidth: 1000, mt: 1 }}
          >
            <Typography variant="caption" color="text.secondary">
              回答将优先给出答案，并附上引用来源供核对。
            </Typography>
            <Typography variant="caption" color="text.secondary">
              最后更新：{formatFullTime(conversation.last_message_at ?? conversation.created_at)}
            </Typography>
          </Stack>
        </Box>
      </Box>

    </Box>
  );
}
