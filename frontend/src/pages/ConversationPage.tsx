import { useCallback, useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
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
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";
import PsychologyOutlinedIcon from "@mui/icons-material/PsychologyOutlined";
import BuildOutlinedIcon from "@mui/icons-material/BuildOutlined";
import AccountTreeOutlinedIcon from "@mui/icons-material/AccountTreeOutlined";
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
import type { AgentApproval, Answer, AnswerBlock, Citation, Conversation, FeedbackRating, Message, ProgressEvent } from "../types/conversations";

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

function toolDisplayName(tool?: string): string {
  if (!tool) return "工具";
  const labels: Record<string, string> = {
    knowledge_search: "知识库检索",
    "knowledge.search": "知识库检索",
    retrieval: "知识检索",
    "skill.load": "技能加载",
    "task.retry": "任务重试",
    "file.list": "文件列表",
    "file.read": "读取文件",
    "text.grep": "文本搜索",
  };
  return labels[tool] ?? tool;
}

function stageDisplayName(stage?: string | null): string {
  const labels: Record<string, string> = {
    UNDERSTANDING: "正在分析问题…",
    RETRIEVING: "正在查询企业知识库…",
    RERANKING: "正在整理检索结果…",
    GENERATING: "正在生成回答…",
    VALIDATING: "正在核对回答来源…",
  };
  return labels[stage || ""] || "正在生成回答…";
}

function eventLabel(event: ProgressEvent): string {
  if (event.type === "thought.summary") return event.message || "分析问题";
  if (event.type === "tool.started") return `调用工具 · ${toolDisplayName(event.tool)}`;
  if (event.type === "tool.completed") return `${toolDisplayName(event.tool)}调用成功`;
  if (event.type === "tool.failed") return `${toolDisplayName(event.tool)}调用失败`;
  if (event.type === "evidence.coverage") return "证据覆盖校验";
  if (event.type === "evidence.selected") return "核对证据";
  if (event.type === "answer.started") return "开始生成回答";
  if (event.type === "answer.completed") return "回答已完成";
  return event.message || event.summary || "处理步骤";
}

function eventIcon(event: ProgressEvent) {
  if (event.type === "tool.failed" || event.status === "FAILED") return <ErrorOutlineIcon fontSize="small" color="error" />;
  if (event.type === "tool.completed" || event.type === "answer.completed") return <CheckCircleOutlineIcon fontSize="small" color="success" />;
  if (event.type === "evidence.coverage") return <CheckCircleOutlineIcon fontSize="small" color="success" />;
  if (event.type === "tool.started") return <BuildOutlinedIcon fontSize="small" color="primary" />;
  return <PsychologyOutlinedIcon fontSize="small" color="primary" />;
}

function formatEventDetail(event: ProgressEvent): string | null {
  const parts = [event.summary || event.message];
  if (event.evidence_count !== undefined) parts.push(`证据 ${event.evidence_count} 条`);
  if (event.missing_terms?.length) parts.push(`待补齐：${event.missing_terms.join("、")}`);
  if (event.duration_ms) parts.push(`${(event.duration_ms / 1000).toFixed(1)} 秒`);
  return parts.filter(Boolean).join(" · ") || null;
}

interface ActivityStep {
  key: string;
  label: string;
  status: "running" | "completed" | "failed";
  event: ProgressEvent;
}

function activityLabel(event: ProgressEvent): string {
  if (event.kind === "tool" || event.type.startsWith("tool.")) {
    return event.display_name || toolDisplayName(event.tool);
  }
  if (event.stage === "UNDERSTANDING") return "分析问题";
  if (event.stage === "GENERATING") return "整理回答";
  if (event.stage === "VALIDATING") return "核对来源";
  if (event.type === "answer.completed") return "生成回答";
  return event.display_name || event.summary || event.message || "执行步骤";
}

function activitySteps(events: ProgressEvent[]): ActivityStep[] {
  const steps: ActivityStep[] = [];
  const byKey = new Map<string, number>();
  for (const event of events) {
    const isTool = event.kind === "tool" || event.type.startsWith("tool.");
    const key = isTool
      ? `tool:${event.step_id || event.event_id || event.tool || event.display_name || "unknown"}`
      : event.type.startsWith("generation.") || event.type === "answer.finalized"
        ? "generation"
        : (event.stage || event.phase) === "UNDERSTANDING"
        ? "analysis"
        : (event.stage || event.phase) === "GENERATING" || event.type.startsWith("answer.")
          ? "generation"
          : `step:${event.step_id || event.stage || event.phase || event.type}`;
    const failed = event.type.endsWith("failed") || event.status === "FAILED";
    const completed = event.type.endsWith("completed") || event.status === "SUCCEEDED";
    const status = failed ? "failed" : completed ? "completed" : "running";
    const existingIndex = byKey.get(key);
    if (existingIndex === undefined) {
      byKey.set(key, steps.length);
      steps.push({ key, label: activityLabel(event), status, event });
      continue;
    }
    const previous = steps[existingIndex];
    steps[existingIndex] = {
      ...previous,
      status: failed ? "failed" : completed ? "completed" : previous.status,
      event: {
        ...previous.event,
        ...event,
        input: event.input ?? previous.event.input,
        output: event.output ?? previous.event.output,
        message: event.message ?? previous.event.message,
      },
    };
  }
  return steps;
}

function activitySummary(events: ProgressEvent[]): string {
  const steps = activitySteps(events);
  const tools = steps.filter((step) => step.key.startsWith("tool:")).length;
  const duration = steps.reduce((total, step) => total + (step.event.duration_ms || 0), 0);
  const durationText = duration > 0 ? ` · ${(duration / 1000).toFixed(1)}s` : "";
  return `已完成 · ${steps.length} 个步骤 · ${tools} 个工具${durationText}`;
}

function hasToolActivity(events: ProgressEvent[]): boolean {
  return events.some((event) => event.kind === "tool" || event.type.startsWith("tool."));
}

function ToolPayload({ event }: { event: ProgressEvent }) {
  if (event.input === undefined && event.output === undefined) return null;
  const renderPayload = (value: unknown) => {
    if (value === undefined) return "—";
    if (typeof value === "string") return value;
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  };
  return (
    <Accordion
      disableGutters
      elevation={0}
      sx={{ mt: 0.75, border: 1, borderColor: "divider", borderRadius: 0.75, "&:before": { display: "none" } }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon fontSize="small" />} sx={{ minHeight: 28, px: 0.75, "& .MuiAccordionSummary-content": { my: 0.25 } }}>
        <Typography variant="caption" color="text.secondary">查看详情</Typography>
      </AccordionSummary>
      <AccordionDetails sx={{ pt: 0.5, px: 0.75, pb: 0.75 }}>
        <Stack spacing={0.25} sx={{ mb: 1 }}>
          <Typography variant="body2" fontWeight={600}>{event.display_name || toolDisplayName(event.tool)}</Typography>
          {event.tool && <Typography variant="caption" color="text.secondary">工具：{event.tool}</Typography>}
          {event.summary && <Typography variant="caption" color="text.secondary">结果：{event.summary}</Typography>}
        </Stack>
        {event.input !== undefined && (
          <Box sx={{ mb: event.output !== undefined ? 0.75 : 0 }}>
            <Typography variant="caption" fontWeight={600} display="block">输入</Typography>
            <Box component="pre" sx={{ m: 0, mt: 0.25, p: 0.75, bgcolor: "grey.50", borderRadius: 0.5, whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: 11, maxHeight: 180, overflow: "auto" }}>
              {renderPayload(event.input)}
            </Box>
          </Box>
        )}
        {event.output !== undefined && (
          <Box>
            <Typography variant="caption" fontWeight={600} display="block">输出</Typography>
            <Box component="pre" sx={{ m: 0, mt: 0.25, p: 0.75, bgcolor: "grey.50", borderRadius: 0.5, whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: 11, maxHeight: 220, overflow: "auto" }}>
              {renderPayload(event.output)}
            </Box>
          </Box>
        )}
      </AccordionDetails>
    </Accordion>
  );
}

function ProcessTimeline({ events, live = false, onRetry }: { events: ProgressEvent[]; live?: boolean; onRetry?: () => void }) {
  // 统一展示 Agent Activity：只展示执行摘要，不展示隐藏思维链。
  if (!hasToolActivity(events)) return null;
  const visible = events
    .filter((event) => event.type === "thought.summary" || event.type.startsWith("tool.") || event.type === "evidence.coverage" || event.type.startsWith("answer.") || (event.type.startsWith("generation.") && event.type !== "generation.delta"))
    .slice(-12);
  if (visible.length === 0) return null;
  const steps = activitySteps(visible);
  const running = live && steps.some((step) => step.status === "running");
  return (
      <Box sx={{ mt: live ? 1.5 : 0, borderTop: live ? 1 : 0, borderColor: "divider", pt: live ? 1.5 : 0 }}>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.25 }}>
        <AccountTreeOutlinedIcon sx={{ fontSize: 16, color: "primary.main" }} />
        <Typography variant="caption" sx={{ color: "primary.main", fontWeight: 700, letterSpacing: "0.04em" }}>
          {live ? "执行过程" : activitySummary(visible)}
        </Typography>
        {running && <CircularProgress size={11} thickness={6} color="primary" />}
      </Stack>
      <Stack spacing={0}>
        {steps.map((step, index) => (
          <Stack key={step.key} direction="row" spacing={1.25} alignItems="stretch" sx={{ minHeight: 42 }}>
            <Box sx={{ width: 18, display: "flex", flexDirection: "column", alignItems: "center" }}>
              <Box sx={{ display: "flex", mt: 0.1, color: step.status === "failed" ? "error.main" : step.status === "completed" ? "success.main" : "primary.main" }}>
                {step.status === "failed" ? <ErrorOutlineIcon fontSize="small" /> : step.status === "completed" ? <CheckCircleOutlineIcon fontSize="small" /> : <CircularProgress size={16} thickness={5} />}
              </Box>
              {index < steps.length - 1 && <Box sx={{ width: 1, flex: 1, bgcolor: "divider", my: 0.4 }} />}
            </Box>
            <Box minWidth={0} sx={{ pb: 1 }}>
              <Typography variant="body2" sx={{ display: "block", lineHeight: 1.35, fontWeight: 600 }}>
                {step.label}
              </Typography>
              {formatEventDetail(step.event) && (
                <Typography variant="caption" color="text.secondary" sx={{ display: "block", lineHeight: 1.4 }}>
                  {formatEventDetail(step.event)}
                </Typography>
              )}
              {!live && step.status === "failed" && onRetry && (
                <Button size="small" variant="text" sx={{ mt: 0.25, px: 0 }} onClick={onRetry}>
                  重试本次回答
                </Button>
              )}
              {step.key.startsWith("tool:") && (
                <ToolPayload event={step.event} />
              )}
            </Box>
          </Stack>
        ))}
      </Stack>
    </Box>
  );
}

function CitationList({ citations }: { citations: Citation[] }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <Accordion
      expanded={expanded}
      onChange={(_event, nextExpanded) => setExpanded(nextExpanded)}
      disableGutters
      elevation={0}
      sx={{ mt: 1.5, border: 1, borderColor: "divider", borderRadius: 1, "&:before": { display: "none" } }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon fontSize="small" />} sx={{ minHeight: 36, px: 1, "& .MuiAccordionSummary-content": { my: 0.5 } }}>
        <Stack direction="row" spacing={0.75} alignItems="center">
          <ArticleOutlinedIcon fontSize="small" color="disabled" />
          <Typography variant="subtitle2">来源文档</Typography>
          <Typography variant="caption" color="text.secondary">
            （{citations.length}）
          </Typography>
        </Stack>
      </AccordionSummary>
      <AccordionDetails sx={{ pt: 0, px: 1, pb: 1 }}>
        <Stack spacing={0.75}>
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
              <Paper key={citation.citation_no} variant="outlined" sx={{ p: 1, borderRadius: 1 }}>
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
  const textContent = (value: AnswerBlock["content"]): string => {
    if (typeof value === "string") return value;
    // Older/generated answers may label structured content as a list or
    // paragraph. Never let a malformed block crash the whole conversation.
    if (value && typeof value === "object") {
      const items = (value as { items?: unknown }).items;
      if (Array.isArray(items)) return items.map(String).join("\n");
      return JSON.stringify(value);
    }
    return "";
  };
  const structuredContent = (() => {
    if (block.content && typeof block.content === "object") return block.content;
    if (typeof block.content === "string") {
      try {
        const parsed = JSON.parse(block.content);
        if (parsed && typeof parsed === "object") return parsed;
      } catch {
        // 普通文本，不是结构化块
      }
    }
    return null;
  })() as { columns?: unknown; rows?: unknown } | null;
  // 兼容模型把表格标成 list/paragraph，但正文仍返回 rows/columns JSON。
  if (
    structuredContent &&
    Array.isArray(structuredContent.columns) &&
    Array.isArray(structuredContent.rows)
  ) {
    const columns = structuredContent.columns.map(String);
    const rows = structuredContent.rows.map((row) =>
      Array.isArray(row) ? row.map(String) : [String(row)],
    );
    return (
      <TableContainer component={Paper} variant="outlined" sx={{ mt: 1 }}>
        <Table size="small">
          <TableHead><TableRow>{columns.map((column) => <TableCell key={column}>{column}</TableCell>)}</TableRow></TableHead>
          <TableBody>{rows.map((row, rowIndex) => <TableRow key={rowIndex}>{row.map((cell, cellIndex) => <TableCell key={cellIndex}>{cell}</TableCell>)}</TableRow>)}</TableBody>
        </Table>
      </TableContainer>
    );
  }
  if (block.type === "paragraph") {
    return (
      <Box
        className="answer-markdown"
        sx={{
          fontSize: 15,
          lineHeight: 1.75,
          overflowX: "auto",
          "& p": { my: 0, mb: 1.25 },
          "& p:last-child": { mb: 0 },
          "& ul, & ol": { mt: 0.5, mb: 1.25, pl: 2.75 },
          "& li": { mb: 0.35 },
          "& h1, & h2, & h3, & h4": { mt: 1.5, mb: 0.75, lineHeight: 1.35 },
          "& blockquote": { m: 0, mb: 1, pl: 1.5, borderLeft: "3px solid", borderColor: "divider", color: "text.secondary" },
          "& table": { width: "100%", borderCollapse: "collapse", my: 1.25, fontSize: 14 },
          "& th, & td": { border: "1px solid", borderColor: "divider", px: 1.25, py: 0.75, textAlign: "left", verticalAlign: "top" },
          "& th": { bgcolor: "grey.50", fontWeight: 700 },
          "& pre": { p: 1.5, borderRadius: 1, bgcolor: "grey.100", overflowX: "auto" },
          "& code": { fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: "0.9em" },
          "& a": { color: "primary.main" },
        }}
      >
        <Markdown
          remarkPlugins={[remarkGfm]}
          components={{
            a: ({ href, children }) => <a href={href} target="_blank" rel="noreferrer">{children}</a>,
          }}
        >
          {textContent(block.content)}
        </Markdown>
      </Box>
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
  const lines = textContent(block.content).split("\n").filter((line) => line.trim());
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
  const [processOpen, setProcessOpen] = useState(false);

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

      {(answer.markdown || answer.draft_text) && answer.status !== "FAILED" ? (
        <Box
          className="answer-markdown"
          sx={{
            mt: 1.5,
            fontSize: 15,
            lineHeight: 1.7,
            "& p": { my: 0, mb: 1 },
            "& table": { width: "100%", borderCollapse: "collapse", my: 1 },
            "& th, & td": { border: "1px solid", borderColor: "divider", px: 1, py: 0.5, textAlign: "left" },
            "& th": { bgcolor: "grey.50" },
          }}
        >
          <Markdown remarkPlugins={[remarkGfm]}>{answer.markdown || answer.draft_text}</Markdown>
        </Box>
      ) : visibleBlocks.length > 0 && (
        <Stack spacing={1} sx={{ mt: 1.5 }}>
          {visibleBlocks.map((block) => (
            <AnswerBlockView key={block.block_id} block={block} />
          ))}
        </Stack>
      )}

      {answer.progress_events && answer.progress_events.length > 0 && hasToolActivity(answer.progress_events) && (
        <Accordion
          expanded={processOpen}
          onChange={(_, expanded) => setProcessOpen(expanded)}
          disableGutters
          elevation={0}
          sx={{ mt: 1.5, border: 1, borderColor: "divider", borderRadius: 1, "&:before": { display: "none" } }}
        >
          <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ minHeight: 42, "& .MuiAccordionSummary-content": { my: 0.75 } }}>
            <Typography variant="caption" color="text.secondary">{activitySummary(answer.progress_events)}</Typography>
          </AccordionSummary>
          <AccordionDetails sx={{ pt: 0 }}>
            <ProcessTimeline events={answer.progress_events} onRetry={onRetry} />
          </AccordionDetails>
        </Accordion>
      )}

      {answer.citations.length > 0 && <CitationList citations={answer.citations} />}

      {/* 反馈 */}
      <Stack
        className="answer-feedback"
        direction="row"
        spacing={0.5}
        alignItems="center"
        sx={{ mt: 1, opacity: { xs: 1, md: 0.35 }, transition: "opacity 160ms ease", "&:hover": { opacity: 1 } }}
      >
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
            maxWidth: 1040,
            py: { xs: 1.5, sm: 2.25 },
            "&:hover .answer-feedback": { opacity: 1 },
          }}
        >
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
  const [progressEvents, setProgressEvents] = useState<ProgressEvent[]>([]);
  const lastProgressSeqRef = useRef(0);
  const toolEvents = progressEvents.filter((event) => event.type.startsWith("tool.")).slice(-4);
  const activeToolEvent = [...toolEvents].reverse().find((event) => {
    if (event.type !== "tool.started") return false;
    return !toolEvents.some((candidate) => candidate.type === "tool.completed" && candidate.tool === event.tool && (candidate.at ?? "") > (event.at ?? ""));
  });

  const bottomRef = useRef<HTMLDivElement>(null);

  /** 拉取消息并检测是否有进行中的回答（刷新/断线后据此恢复 SSE 订阅）。 */
  const refreshMessages = useCallback(async () => {
    if (!conversationId) return;
    const msgs = await getMessages(conversationId);
    setMessages(msgs.items);
    const active = msgs.items.find((m) => m.answer && isInProgress(m.answer.status));
    if (active?.answer) {
      const a = active.answer;
      setProgressEvents(a.progress_events ?? []);
      lastProgressSeqRef.current = Math.max(0, ...(a.progress_events ?? []).map((event) => event.seq ?? 0));
      setStreaming({
        answer_id: a.id,
        status: a.status,
        progress_stage: a.progress_stage ?? null,
        progress_message: a.progress_message ?? null,
        answer_type: a.answer_type,
        summary: a.summary,
        blocks: a.blocks,
        citations: a.citations,
        degradation_flags: a.degradation_flags,
        progress_events: a.progress_events,
      });
    } else {
      setStreaming(null);
    }
  }, [conversationId]);

  const load = useCallback(async (signal?: AbortSignal) => {
    if (!conversationId) return;
    // 先清空上一会话的进行中状态，避免切换会话时短暂展示旧答案的阶段。
    setStreaming(null);
    setProgressEvents([]);
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
        setProgressEvents(a.progress_events ?? []);
        lastProgressSeqRef.current = Math.max(0, ...(a.progress_events ?? []).map((event) => event.seq ?? 0));
        setStreaming({
          answer_id: a.id,
          status: a.status,
          progress_stage: a.progress_stage ?? null,
          progress_message: a.progress_message ?? null,
          answer_type: a.answer_type,
          summary: a.summary,
          blocks: a.blocks,
          citations: a.citations,
          degradation_flags: a.degradation_flags,
          progress_events: a.progress_events,
        });
      } else {
    setStreaming(null);
    setProgressEvents([]);
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
        setProgressEvents(answer.progress_events ?? []);
        lastProgressSeqRef.current = Math.max(0, ...(answer.progress_events ?? []).map((event) => event.seq ?? 0));
        setStreaming({
          answer_id: answer.id,
          status: answer.status,
          progress_stage: answer.progress_stage ?? null,
          progress_message: answer.progress_message ?? null,
          answer_type: answer.answer_type,
          summary: answer.summary,
          draft_text: answer.draft_text,
          blocks: answer.blocks,
          citations: answer.citations,
          degradation_flags: answer.degradation_flags,
          progress_events: answer.progress_events,
        });
        if (!isInProgress(answer.status)) {
          close();
          void refreshMessages();
        }
      },
      onStatus: (payload) => {
        if (cancelled) return;
        setStreaming((prev) =>
          prev ? { ...prev, status: payload.status, progress_stage: payload.progress_stage, progress_message: payload.progress_message ?? prev.progress_message } : prev,
        );
      },
      onDelta: (payload) => {
        if (cancelled) return;
        setStreaming((prev) => (prev ? { ...prev, draft_text: payload.text } : prev));
      },
      onProgress: (payload) => {
        if (cancelled) return;
        if (payload.type === "generation.delta") {
          const output = payload.output;
          const delta = output && typeof output === "object" && "text" in output
            ? String((output as { text?: unknown }).text ?? "")
            : "";
          if (delta) {
            setStreaming((prev) => prev ? { ...prev, draft_text: `${prev.draft_text ?? ""}${delta}` } : prev);
          }
        }
        setProgressEvents((prev) => {
          if (payload.seq !== undefined && payload.seq <= lastProgressSeqRef.current) return prev;
          if (payload.event_id && prev.some((event) => event.event_id === payload.event_id)) return prev;
          if (payload.seq !== undefined) lastProgressSeqRef.current = payload.seq;
          return [...prev, payload].slice(-40);
        });
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
        width: { xs: "100%", md: "calc(100% - 32px)" },
        maxWidth: 1240,
        height: "100%",
        minHeight: 0,
        mx: "auto",
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
        sx={{ width: "100%", maxWidth: 1040, mb: 1.5, flexShrink: 0 }}
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
            "& > *": { width: "100%", maxWidth: 1040 },
          }}
        >
          {messages.length === 0 ? (
            <Box sx={{ py: 6 }}>
              <EmptyState
                title="开始提问"
                description="在下方输入问题，系统会按需调用已启用的工具并生成答案。"
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
            <Paper elevation={0} sx={{ p: 0.5, bgcolor: "transparent", border: 0 }}>
              <Stack direction="row" spacing={1.5} alignItems="flex-start">
                <CircularProgress size={18} thickness={5} />
                <Box minWidth={0}>
                  <Typography variant="subtitle2">
                    {activeToolEvent
                      ? `正在查询${toolDisplayName(activeToolEvent.tool)}…`
                      : streaming.progress_message || stageDisplayName(streaming.progress_stage)}
                  </Typography>
                  <ProcessTimeline events={progressEvents} live />
                  {streaming.draft_text && (
                    <Box className="answer-markdown" sx={{ mt: 1, fontSize: 15, lineHeight: 1.7, "& p": { my: 0, mb: 1 }, "& table": { width: "100%", borderCollapse: "collapse", my: 1 }, "& th, & td": { border: "1px solid", borderColor: "divider", px: 1, py: 0.5, textAlign: "left" }, "& th": { bgcolor: "grey.50" } }}>
                      <Markdown remarkPlugins={[remarkGfm]}>{streaming.draft_text}</Markdown>
                    </Box>
                  )}
                  <Typography variant="caption" color="text.secondary">
                    {streaming.degradation_flags.length > 0
                      ? "部分资料服务不可用，已使用可用结果继续回答。"
                      : "答案和来源会在生成过程中逐步显示。"}
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
          <Stack direction="row" spacing={1.5} alignItems="flex-end" sx={{ maxWidth: 1040, mx: "auto" }}>
            <TextField
              placeholder="输入消息，Enter 发送，Shift+Enter 换行"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              multiline
              minRows={1}
              maxRows={4}
              fullWidth
              disabled={sending || !!streaming}
              inputProps={{ "aria-label": "继续追问" }}
              sx={{
                "& .MuiOutlinedInput-root": {
                  bgcolor: "#ffffff",
                },
              }}
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
