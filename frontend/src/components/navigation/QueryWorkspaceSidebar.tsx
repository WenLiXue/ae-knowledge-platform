import { useEffect, useState } from "react";
import { Link as RouterLink, useLocation, useNavigate } from "react-router-dom";
import {
  Box,
  Button,
  CircularProgress,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  IconButton,
  Menu,
  MenuItem,
  List,
  ListItemButton,
  ListItemText,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import AssignmentOutlinedIcon from "@mui/icons-material/AssignmentOutlined";
import ExtensionOutlinedIcon from "@mui/icons-material/ExtensionOutlined";
import BiotechOutlinedIcon from "@mui/icons-material/BiotechOutlined";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import FactCheckOutlinedIcon from "@mui/icons-material/FactCheckOutlined";
import FolderOutlinedIcon from "@mui/icons-material/FolderOutlined";
import ListAltOutlinedIcon from "@mui/icons-material/ListAltOutlined";
import MoreHorizIcon from "@mui/icons-material/MoreHoriz";
import LogoutOutlinedIcon from "@mui/icons-material/LogoutOutlined";
import PeopleOutlinedIcon from "@mui/icons-material/PeopleOutlined";
import ReceiptLongOutlinedIcon from "@mui/icons-material/ReceiptLongOutlined";
import SearchIcon from "@mui/icons-material/Search";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import SmartToyOutlinedIcon from "@mui/icons-material/SmartToyOutlined";
import TuneOutlinedIcon from "@mui/icons-material/TuneOutlined";
import UploadFileOutlinedIcon from "@mui/icons-material/UploadFileOutlined";
import { getErrorMessage } from "../../api/client";
import { deleteConversation, updateConversation } from "../../api/conversations";
import { useAuth } from "../../auth/AuthContext";
import { useConversationWorkspace } from "../../conversations/ConversationWorkspaceContext";

interface NavItem {
  to: string;
  label: string;
  icon: React.ReactNode;
}

const PRIMARY_ITEMS: NavItem[] = [
  { to: "/search", label: "知识查询", icon: <SearchIcon fontSize="small" /> },
  { to: "/diagnosis", label: "问题诊断", icon: <BiotechOutlinedIcon fontSize="small" /> },
];

const KNOWLEDGE_ITEMS: NavItem[] = [
  { to: "/documents/import", label: "文档导入", icon: <UploadFileOutlinedIcon fontSize="small" /> },
  { to: "/documents", label: "文档库", icon: <FolderOutlinedIcon fontSize="small" /> },
  { to: "/admin/pending-classification", label: "待分类确认", icon: <FactCheckOutlinedIcon fontSize="small" /> },
];

const ADMIN_ITEMS: NavItem[] = [
  { to: "/admin/conversations", label: "全部会话", icon: <AssignmentOutlinedIcon fontSize="small" /> },
  { to: "/admin/agent-capabilities", label: "Agent 能力", icon: <ExtensionOutlinedIcon fontSize="small" /> },
  { to: "/admin/tasks", label: "处理任务", icon: <AssignmentOutlinedIcon fontSize="small" /> },
  { to: "/admin/knowledge-config", label: "知识库配置", icon: <TuneOutlinedIcon fontSize="small" /> },
  { to: "/admin/llm-config", label: "LLM 配置", icon: <SmartToyOutlinedIcon fontSize="small" /> },
  { to: "/admin/system-logs", label: "系统日志", icon: <ListAltOutlinedIcon fontSize="small" /> },
  { to: "/admin/users", label: "用户管理", icon: <PeopleOutlinedIcon fontSize="small" /> },
  { to: "/admin/audit-logs", label: "审计日志", icon: <ReceiptLongOutlinedIcon fontSize="small" /> },
];

function isNavActive(pathname: string, item: NavItem): boolean {
  // 知识查询在整个会话工作区（含会话页）均处于激活态。
  if (item.to === "/search") {
    return pathname === "/search" || pathname.startsWith("/conversations/");
  }
  // 文档详情归属文档库，但导入页只高亮“文档导入”。
  if (item.to === "/documents") {
    return pathname.startsWith("/documents") && !pathname.startsWith("/documents/import");
  }
  return pathname === item.to || pathname.startsWith(`${item.to}/`);
}

function formatTime(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

interface QueryWorkspaceSidebarProps {
  /** 移动端临时 Drawer 导航后关闭。 */
  onNavigate?: () => void;
}

/**
 * 查询工作区侧栏：新建查询 + 主要入口 + 最近会话。
 * 会话数据来自 ConversationWorkspaceContext（唯一状态所有者），本组件不发起请求。
 */
export function QueryWorkspaceSidebar({ onNavigate }: QueryWorkspaceSidebarProps) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { conversations, loading, error, refreshConversations } = useConversationWorkspace();
  const inKnowledgeSection = KNOWLEDGE_ITEMS.some((item) => isNavActive(pathname, item));
  const inAdminSection = ADMIN_ITEMS.some((item) => isNavActive(pathname, item));
  const showRecentConversations =
    pathname === "/search" || pathname.startsWith("/conversations/");
  const [knowledgeOpen, setKnowledgeOpen] = useState(inKnowledgeSection);
  const [adminOpen, setAdminOpen] = useState(inAdminSection);
  const [menuAnchor, setMenuAnchor] = useState<HTMLElement | null>(null);
  const [menuConversationId, setMenuConversationId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingValue, setEditingValue] = useState("");
  const [pendingDelete, setPendingDelete] = useState<{ id: string; title: string } | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (inKnowledgeSection) setKnowledgeOpen(true);
    if (inAdminSection) setAdminOpen(true);
  }, [inAdminSection, inKnowledgeSection]);

  const currentConversationId = pathname.startsWith("/conversations/")
    ? pathname.split("/")[2]
    : null;

  const handleNewQuery = () => {
    navigate("/search");
    onNavigate?.();
  };

  const closeMenu = () => {
    setMenuAnchor(null);
    setMenuConversationId(null);
  };

  const startRename = () => {
    const conversation = conversations.find((item) => item.id === menuConversationId);
    if (!conversation) return;
    setEditingId(conversation.id);
    setEditingValue(conversation.title);
    closeMenu();
  };

  const saveRename = async () => {
    const title = editingValue.trim();
    if (!editingId || !title) {
      setEditingId(null);
      return;
    }
    try {
      await updateConversation(editingId, { title });
      await refreshConversations();
    } finally {
      setEditingId(null);
    }
  };

  const removeConversation = async () => {
    const id = menuConversationId;
    const conversation = conversations.find((item) => item.id === id);
    closeMenu();
    if (id && conversation) setPendingDelete({ id, title: conversation.title });
  };

  const confirmDeleteConversation = async () => {
    if (!pendingDelete || deleting) return;
    setDeleting(true);
    try {
      await deleteConversation(pendingDelete.id);
      await refreshConversations();
      if (currentConversationId === pendingDelete.id) navigate("/search");
      setPendingDelete(null);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* 品牌 */}
      <Box sx={{ px: 2.5, py: 2, display: "flex", alignItems: "center", gap: 1.5 }}>
        <Box
          component="img"
          src="/workbench-icon.svg"
          alt="智能工作台"
          sx={{ width: 36, height: 36, flexShrink: 0 }}
        />
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="subtitle1" sx={{ lineHeight: 1.2, fontWeight: 700 }}>
            智能工作台
          </Typography>
          <Typography variant="caption" color="text.secondary" noWrap display="block">
            AE Intelligent Workbench
          </Typography>
        </Box>
      </Box>
      <Divider />

      {/* 新建查询 */}
      <Box sx={{ px: 1.5, pt: 1.5 }}>
        <Button
          fullWidth
          onClick={handleNewQuery}
          startIcon={<AddIcon />}
          sx={{
            justifyContent: "flex-start",
            minHeight: 40,
            px: 1.25,
            border: 1,
            borderColor: "divider",
            borderRadius: 1.5,
            bgcolor: "background.paper",
            color: "text.primary",
            fontWeight: 600,
            "&:hover": { bgcolor: "#fafafa" },
          }}
        >
          新建查询
        </Button>
      </Box>

      {/* 主要入口 */}
      <Box
        component="nav"
        aria-label="查询工作区导航"
        sx={{ px: 1.5, pt: 1, pb: 1.5, borderBottom: 1, borderColor: "divider" }}
      >
        <Stack spacing={0.25}>
          {PRIMARY_ITEMS.map((item) => {
            const active = isNavActive(pathname, item);
            return (
              <Button
                key={item.to}
                component={RouterLink}
                to={item.to}
                onClick={onNavigate}
                aria-current={active ? "page" : undefined}
                startIcon={item.icon}
                sx={{
                  justifyContent: "flex-start",
                  minHeight: 36,
                  px: 1.25,
                  borderRadius: 1.5,
                  color: "text.primary",
                  bgcolor: active ? "#e2e2df" : "transparent",
                  fontWeight: active ? 600 : 500,
                  "&:hover": { bgcolor: active ? "#e2e2df" : "#e9e9e6" },
                }}
              >
                {item.label}
              </Button>
            );
          })}

          <Button
            onClick={() => setKnowledgeOpen((open) => !open)}
            aria-expanded={knowledgeOpen}
            aria-controls="knowledge-navigation"
            startIcon={<FolderOutlinedIcon fontSize="small" />}
            endIcon={knowledgeOpen ? <ExpandLessIcon /> : <ExpandMoreIcon />}
            sx={{
              justifyContent: "flex-start",
              minHeight: 36,
              px: 1.25,
              borderRadius: 1.5,
              color: "text.primary",
              bgcolor: inKnowledgeSection ? "#e2e2df" : "transparent",
              fontWeight: inKnowledgeSection ? 600 : 500,
              "& .MuiButton-endIcon": { ml: "auto" },
              "&:hover": { bgcolor: inKnowledgeSection ? "#e2e2df" : "#e9e9e6" },
            }}
          >
            知识管理
          </Button>
          <Collapse in={knowledgeOpen} timeout="auto" unmountOnExit>
            <Stack id="knowledge-navigation" spacing={0.25} sx={{ ml: 2.25, pl: 1, borderLeft: 1, borderColor: "divider" }}>
              {KNOWLEDGE_ITEMS.map((item) => {
                const active = isNavActive(pathname, item);
                return (
                  <Button
                    key={item.to}
                    component={RouterLink}
                    to={item.to}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    startIcon={item.icon}
                    sx={{
                      justifyContent: "flex-start",
                      minHeight: 34,
                      px: 1,
                      borderRadius: 1.5,
                      color: "text.primary",
                      bgcolor: active ? "#e2e2df" : "transparent",
                      fontWeight: active ? 600 : 500,
                      "&:hover": { bgcolor: active ? "#e2e2df" : "#e9e9e6" },
                    }}
                  >
                    {item.label}
                  </Button>
                );
              })}
            </Stack>
          </Collapse>

          {user?.role === "admin" && <>
              <Button
                onClick={() => setAdminOpen((open) => !open)}
                aria-expanded={adminOpen}
                aria-controls="admin-navigation"
                startIcon={<TuneOutlinedIcon fontSize="small" />}
                endIcon={adminOpen ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                sx={{
                  justifyContent: "flex-start",
                  minHeight: 36,
                  px: 1.25,
                  borderRadius: 1.5,
                  color: "text.primary",
                  bgcolor: inAdminSection ? "#e2e2df" : "transparent",
                  fontWeight: inAdminSection ? 600 : 500,
                  "& .MuiButton-endIcon": { ml: "auto" },
                  "&:hover": { bgcolor: inAdminSection ? "#e2e2df" : "#e9e9e6" },
                }}
              >
                系统管理
              </Button>
              <Collapse in={adminOpen} timeout="auto" unmountOnExit>
                <Stack id="admin-navigation" spacing={0.25} sx={{ ml: 2.25, pl: 1, borderLeft: 1, borderColor: "divider" }}>
                  {ADMIN_ITEMS.map((item) => {
                    const active = isNavActive(pathname, item);
                    return (
                      <Button
                        key={item.to}
                        component={RouterLink}
                        to={item.to}
                        onClick={onNavigate}
                        aria-current={active ? "page" : undefined}
                        startIcon={item.icon}
                        sx={{
                          justifyContent: "flex-start",
                          minHeight: 34,
                          px: 1,
                          borderRadius: 1.5,
                          color: "text.primary",
                          bgcolor: active ? "#e2e2df" : "transparent",
                          fontWeight: active ? 600 : 500,
                          "&:hover": { bgcolor: active ? "#e2e2df" : "#e9e9e6" },
                        }}
                      >
                        {item.label}
                      </Button>
                    );
                  })}
                </Stack>
              </Collapse>
          </>}
        </Stack>
      </Box>

      {/* 最近会话 */}
      <Box sx={{ flexGrow: 1, minHeight: 0, overflowY: "auto", py: showRecentConversations ? 1.5 : 0, px: 1 }}>
        {showRecentConversations ? (
          <>
        <Typography
          variant="overline"
          sx={{ display: "block", px: 1, pb: 0.5, color: "text.secondary" }}
        >
          最近会话
        </Typography>

        {error ? (
          <Stack spacing={1} sx={{ px: 1, py: 1 }}>
            <Typography variant="caption" color="error.main">
              {getErrorMessage(error)}
            </Typography>
            <Box>
              <Button size="small" onClick={() => void refreshConversations()}>
                重试
              </Button>
            </Box>
          </Stack>
        ) : loading && conversations.length === 0 ? (
          <Stack direction="row" spacing={1} alignItems="center" sx={{ px: 1.25, py: 1 }}>
            <CircularProgress size={16} />
            <Typography variant="caption" color="text.secondary">
              正在加载会话…
            </Typography>
          </Stack>
        ) : conversations.length === 0 ? (
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", px: 1.25, py: 1 }}>
            暂无会话，开始一次新查询吧。
          </Typography>
        ) : (
          <List disablePadding aria-label="最近会话">
            {conversations.map((conversation) => {
              const current = currentConversationId === conversation.id;
              return (
                <ListItemButton
                  key={conversation.id}
                  component={RouterLink}
                  to={`/conversations/${conversation.id}`}
                  selected={current}
                  aria-current={current ? "page" : undefined}
                  onClick={onNavigate}
                  sx={{
                    borderRadius: 1.5,
                    mb: 0.25,
                    px: 1,
                    py: 0.5,
                    minHeight: 44,
                    "&.Mui-selected": {
                      bgcolor: "#e2e2df",
                      color: "inherit",
                      "&:hover": { bgcolor: "#e2e2df" },
                    },
                    "&:hover .conversation-actions": { opacity: 1 },
                  }}
                >
                  {editingId === conversation.id ? (
                    <TextField
                      autoFocus
                      fullWidth
                      size="small"
                      value={editingValue}
                      onChange={(event) => setEditingValue(event.target.value)}
                      onClick={(event) => event.preventDefault()}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") { event.preventDefault(); void saveRename(); }
                        if (event.key === "Escape") setEditingId(null);
                      }}
                      inputProps={{ "aria-label": "会话名称" }}
                    />
                  ) : (
                    <ListItemText
                      primary={conversation.title}
                      secondary={formatTime(conversation.last_message_at)}
                      primaryTypographyProps={{ noWrap: true, fontSize: 13, fontWeight: 560 }}
                      secondaryTypographyProps={{ fontSize: 11, color: "text.secondary", mt: 0.25 }}
                    />
                  )}
                  {editingId !== conversation.id && (
                    <IconButton
                      className="conversation-actions"
                      size="small"
                      aria-label={`管理会话 ${conversation.title}`}
                      onClick={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        setMenuAnchor(event.currentTarget);
                        setMenuConversationId(conversation.id);
                      }}
                      sx={{ opacity: 0, transition: "opacity 120ms", ml: 0.5 }}
                    >
                      <MoreHorizIcon fontSize="small" />
                    </IconButton>
                  )}
                </ListItemButton>
              );
            })}
          </List>
        )}
        <Menu anchorEl={menuAnchor} open={Boolean(menuAnchor)} onClose={closeMenu}>
          <MenuItem onClick={startRename}><EditOutlinedIcon fontSize="small" sx={{ mr: 1 }} />重命名</MenuItem>
          <MenuItem onClick={() => void removeConversation()} sx={{ color: "error.main" }}>
            <DeleteOutlineIcon fontSize="small" sx={{ mr: 1 }} />删除会话
          </MenuItem>
        </Menu>
        <Dialog
          open={Boolean(pendingDelete)}
          onClose={() => !deleting && setPendingDelete(null)}
          maxWidth="xs"
          fullWidth
        >
          <DialogTitle>删除会话？</DialogTitle>
          <DialogContent>
            <DialogContentText>
              确定删除“{pendingDelete?.title}”吗？删除后将无法恢复。
            </DialogContentText>
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setPendingDelete(null)} disabled={deleting}>取消</Button>
            <Button color="error" variant="contained" onClick={() => void confirmDeleteConversation()} disabled={deleting}>
              {deleting ? <CircularProgress size={18} color="inherit" /> : "删除"}
            </Button>
          </DialogActions>
        </Dialog>
          </>
        ) : null}
      </Box>

      <Divider />
      {/* 当前用户 */}
      <Box sx={{ px: 2, py: 1.5 }}>
        {user && (
          <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="body2" fontWeight={600} noWrap>
                {user.display_name}
              </Typography>
              <Typography variant="caption" color="text.secondary" noWrap display="block">
                {user.role === "admin" ? "管理员" : user.username}
              </Typography>
            </Box>
            <Tooltip title="个人设置">
              <IconButton size="small" component={RouterLink} to="/settings/profile" onClick={onNavigate}>
                <SettingsOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
            <Tooltip title="退出登录">
              <IconButton size="small" onClick={() => void logout()}>
                <LogoutOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Stack>
        )}
      </Box>
    </Box>
  );
}
