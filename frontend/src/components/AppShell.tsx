import { useState } from "react";
import { Link as RouterLink, Outlet, useLocation } from "react-router-dom";
import {
  AppBar,
  Box,
  Container,
  Divider,
  Drawer,
  IconButton,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Stack,
  Toolbar,
  Tooltip,
  Typography,
} from "@mui/material";
import MenuIcon from "@mui/icons-material/Menu";
import SearchIcon from "@mui/icons-material/Search";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import FolderOutlinedIcon from "@mui/icons-material/FolderOutlined";
import BiotechOutlinedIcon from "@mui/icons-material/BiotechOutlined";
import AssignmentOutlinedIcon from "@mui/icons-material/AssignmentOutlined";
import FactCheckOutlinedIcon from "@mui/icons-material/FactCheckOutlined";
import TuneOutlinedIcon from "@mui/icons-material/TuneOutlined";
import SmartToyOutlinedIcon from "@mui/icons-material/SmartToyOutlined";
import PeopleOutlinedIcon from "@mui/icons-material/PeopleOutlined";
import ReceiptLongOutlinedIcon from "@mui/icons-material/ReceiptLongOutlined";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import LogoutOutlinedIcon from "@mui/icons-material/LogoutOutlined";
import { useAuth } from "../auth/AuthContext";

const DRAWER_WIDTH = 248;

interface NavItem {
  to: string;
  label: string;
  icon: React.ReactNode;
  /** 精确匹配（不匹配子路径）。 */
  exact?: boolean;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    label: "知识工作区",
    items: [
      { to: "/search", label: "知识查询", icon: <SearchIcon /> },
      { to: "/documents/import", label: "文档导入", icon: <UploadFileIcon /> },
      { to: "/documents", label: "已入库文档", icon: <FolderOutlinedIcon /> },
      { to: "/diagnosis", label: "问题诊断", icon: <BiotechOutlinedIcon /> },
    ],
  },
  {
    label: "系统管理",
    items: [
      { to: "/admin/tasks", label: "处理任务", icon: <AssignmentOutlinedIcon /> },
      { to: "/admin/pending-classification", label: "待分类确认", icon: <FactCheckOutlinedIcon /> },
      { to: "/admin/knowledge-config", label: "知识库配置", icon: <TuneOutlinedIcon /> },
      { to: "/admin/llm-config", label: "LLM 配置", icon: <SmartToyOutlinedIcon /> },
      { to: "/admin/users", label: "用户管理", icon: <PeopleOutlinedIcon /> },
      { to: "/admin/audit-logs", label: "审计日志", icon: <ReceiptLongOutlinedIcon /> },
    ],
  },
  {
    label: "个人",
    items: [{ to: "/settings/profile", label: "个人设置", icon: <SettingsOutlinedIcon /> }],
  },
];

/**
 * 判断导航项是否处于激活状态。
 * “已入库文档”特殊处理：/documents 与 /documents/:id 激活，但 /documents/import 不激活。
 */
function isActive(pathname: string, item: NavItem): boolean {
  if (item.to === "/documents") {
    return pathname.startsWith("/documents") && !pathname.startsWith("/documents/import");
  }
  if (item.exact) {
    return pathname === item.to;
  }
  return pathname === item.to || pathname.startsWith(`${item.to}/`);
}

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const { user, logout } = useAuth();
  const pathname = useLocation().pathname;

  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <Box sx={{ px: 2.5, py: 2.5, display: "flex", alignItems: "center", gap: 1.5 }}>
        <Box
          sx={{
            width: 34,
            height: 34,
            borderRadius: 1.5,
            bgcolor: "primary.main",
            color: "#fff",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 800,
            fontSize: 15,
            flexShrink: 0,
          }}
        >
          AE
        </Box>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="subtitle1" sx={{ lineHeight: 1.2, fontWeight: 700 }}>
            知识智能平台
          </Typography>
          <Typography variant="caption" color="text.secondary" noWrap display="block">
            AE Knowledge Platform
          </Typography>
        </Box>
      </Box>
      <Divider />

      <Box sx={{ flexGrow: 1, overflowY: "auto", px: 1.5, py: 1.5 }}>
        {NAV_GROUPS.map((group) => (
          <Box key={group.label} sx={{ mb: 1.5 }}>
            <Typography
              variant="overline"
              sx={{ px: 1, color: "text.secondary", letterSpacing: 0.06 }}
            >
              {group.label}
            </Typography>
            <List disablePadding>
              {group.items.map((item) => {
                const selected = isActive(pathname, item);
                return (
                  <ListItemButton
                    key={item.to}
                    component={RouterLink}
                    to={item.to}
                    selected={selected}
                    onClick={onNavigate}
                    sx={{
                      borderRadius: 2,
                      mb: 0.5,
                      "&.Mui-selected": {
                        bgcolor: "primary.main",
                        color: "#fff",
                        "& .MuiListItemIcon-root": { color: "#fff" },
                        "&:hover": { bgcolor: "primary.dark" },
                      },
                    }}
                  >
                    <ListItemIcon sx={{ minWidth: 34, color: "inherit" }}>{item.icon}</ListItemIcon>
                    <ListItemText
                      primary={item.label}
                      primaryTypographyProps={{ fontSize: 14, fontWeight: 600 }}
                    />
                  </ListItemButton>
                );
              })}
            </List>
          </Box>
        ))}
      </Box>

      <Divider />
      <Box sx={{ px: 2, py: 1.5 }}>
        {user && (
          <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="body2" fontWeight={600} noWrap>
                {user.display_name}
              </Typography>
              <Typography variant="caption" color="text.secondary" noWrap display="block">
                {user.username}
              </Typography>
            </Box>
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

/** 统一应用外壳：桌面常驻 / 移动临时侧边导航 + 内容区。 */
export function AppShell() {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <Box sx={{ display: "flex", minHeight: "100vh" }}>
      <AppBar
        position="fixed"
        elevation={0}
        sx={{
          zIndex: (t) => t.zIndex.drawer + 1,
          bgcolor: "background.paper",
          color: "text.primary",
          borderBottom: 1,
          borderColor: "divider",
          display: { md: "none" },
        }}
      >
        <Toolbar>
          <IconButton
            edge="start"
            color="inherit"
            onClick={() => setMobileOpen(true)}
            sx={{ mr: 1 }}
            aria-label="打开菜单"
          >
            <MenuIcon />
          </IconButton>
          <Typography variant="subtitle1" fontWeight={700}>
            AE 知识智能平台
          </Typography>
        </Toolbar>
      </AppBar>

      <Box component="nav" sx={{ width: { md: DRAWER_WIDTH }, flexShrink: { md: 0 } }} aria-label="主导航">
        <Drawer
          variant="permanent"
          open
          sx={{
            display: { xs: "none", md: "block" },
            "& .MuiDrawer-paper": {
              width: DRAWER_WIDTH,
              boxSizing: "border-box",
              borderRight: 1,
              borderColor: "divider",
            },
          }}
        >
          <SidebarContent />
        </Drawer>
        <Drawer
          variant="temporary"
          open={mobileOpen}
          onClose={() => setMobileOpen(false)}
          ModalProps={{ keepMounted: true }}
          sx={{
            display: { xs: "block", md: "none" },
            "& .MuiDrawer-paper": { width: DRAWER_WIDTH, boxSizing: "border-box" },
          }}
        >
          <SidebarContent onNavigate={() => setMobileOpen(false)} />
        </Drawer>
      </Box>

      <Box component="main" sx={{ flexGrow: 1, minWidth: 0 }}>
        <Toolbar sx={{ display: { md: "none" } }} />
        <Container maxWidth="lg" sx={{ px: { xs: 2, sm: 3 }, py: { xs: 3, md: 4 } }}>
          <Outlet />
        </Container>
      </Box>
    </Box>
  );
}
