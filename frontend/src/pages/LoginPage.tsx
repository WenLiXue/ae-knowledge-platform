import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Divider,
  FormControlLabel,
  Paper,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import { getErrorMessage } from "../api/client";
import { useAuth } from "../auth/AuthContext";

interface LocationState {
  from?: { pathname: string };
}

type LoginTab = "password" | "feishu";

/** 登录页：账号密码 / 飞书扫码（当前为 Mock 登录，见 api/auth.ts）。 */
export function LoginPage() {
  const { user, initializing, login, loginWithFeishu } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as LocationState | null)?.from?.pathname ?? "/search";

  const [tab, setTab] = useState<LoginTab>("password");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feishuState, setFeishuState] = useState<"idle" | "waiting">("idle");

  if (!initializing && user) {
    return <Navigate to={from} replace />;
  }

  const handlePasswordSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await login(username, password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(getErrorMessage(err, "登录失败，请稍后重试。"));
    } finally {
      setLoading(false);
    }
  };

  const handleFeishuOpen = async () => {
    setError(null);
    // MOCK: 真实实现会打开飞书授权窗口；当前直接进入“等待确认”状态。
    setFeishuState("waiting");
  };

  const handleFeishuComplete = async () => {
    setLoading(true);
    setError(null);
    try {
      // MOCK: 模拟用户在飞书客户端完成扫码确认。
      await loginWithFeishu();
      navigate(from, { replace: true });
    } catch (err) {
      setError(getErrorMessage(err, "飞书登录失败，请重试。"));
      setFeishuState("idle");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Stack
      direction={{ xs: "column", md: "row" }}
      spacing={{ xs: 4, md: 6 }}
      sx={{ width: "100%", maxWidth: 920, alignItems: "center" }}
    >
      {/* 品牌介绍 */}
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
          <Box
            sx={{
              width: 44,
              height: 44,
              borderRadius: 2,
              bgcolor: "primary.main",
              color: "#fff",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontWeight: 800,
              fontSize: 18,
            }}
          >
            AE
          </Box>
          <Typography variant="overline" color="text.secondary" sx={{ letterSpacing: 0.08 }}>
            PRODUCT KNOWLEDGE
          </Typography>
        </Box>
        <Typography variant="h4" component="h1" sx={{ mt: 2 }}>
          AE 内部知识平台
        </Typography>
        <Typography color="text.secondary" sx={{ mt: 1, maxWidth: 420, lineHeight: 1.7 }}>
          统一查询产品知识，沉淀文档经验，为问题分析提供可靠依据。
        </Typography>
      </Box>

      {/* 登录卡片 */}
      <Paper variant="outlined" sx={{ width: "100%", maxWidth: 400, p: 3 }}>
        <Typography variant="h6" component="h2">
          欢迎登录
        </Typography>
        <Typography color="text.secondary" variant="body2" sx={{ mt: 0.5 }}>
          请选择适合你的登录方式
        </Typography>

        <Tabs
          value={tab}
          onChange={(_event, value: LoginTab) => {
            setTab(value);
            setError(null);
          }}
          sx={{ mt: 2, mb: 2, borderBottom: 1, borderColor: "divider" }}
        >
          <Tab label="账号密码" value="password" />
          <Tab label="飞书扫码" value="feishu" />
        </Tabs>

        {tab === "password" ? (
          <form onSubmit={handlePasswordSubmit}>
            <Stack spacing={2}>
              <TextField
                label="账号"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="请输入账号"
                autoComplete="username"
                fullWidth
                size="small"
                required
              />
              <TextField
                label="密码"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="请输入密码"
                autoComplete="current-password"
                fullWidth
                size="small"
                required
              />
              <FormControlLabel
                control={
                  <Checkbox size="small" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
                }
                label={<Typography variant="body2">记住账号</Typography>}
              />
              <Button type="submit" variant="contained" disabled={loading} size="large" fullWidth>
                {loading ? "登录中…" : "登录"}
              </Button>
            </Stack>
          </form>
        ) : (
          <Stack spacing={2}>
            <Box
              sx={{
                py: 2,
                textAlign: "center",
                bgcolor: "primary.light",
                borderRadius: 2,
                color: "primary.main",
                fontWeight: 700,
              }}
            >
              飞书
            </Box>
            <Typography variant="body2" color="text.secondary" textAlign="center">
              点击后打开飞书认证页面，并在飞书客户端扫码确认。
            </Typography>
            {feishuState === "idle" ? (
              <Button variant="contained" onClick={handleFeishuOpen} size="large" fullWidth>
                打开飞书扫码登录
              </Button>
            ) : (
              <Stack spacing={1.5}>
                <Alert severity="info">认证窗口已打开，请在飞书客户端完成扫码。</Alert>
                <Button variant="outlined" onClick={handleFeishuComplete} disabled={loading} fullWidth>
                  {loading ? "登录中…" : "原型：模拟扫码完成"}
                </Button>
              </Stack>
            )}
            <Divider />
            <Typography variant="caption" color="text.secondary">
              系统使用飞书 user_id 识别用户；首次扫码自动创建账号，已存在账号则直接登录。
            </Typography>
          </Stack>
        )}

        {error && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {error}
          </Alert>
        )}

        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ display: "block", mt: 3, textAlign: "center" }}
        >
          仅供公司内部人员使用
        </Typography>
      </Paper>
    </Stack>
  );
}
