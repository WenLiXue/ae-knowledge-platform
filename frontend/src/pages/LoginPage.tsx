import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Checkbox,
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
import { FeishuQrLogin } from "../components/FeishuQrLogin";

interface LocationState {
  from?: { pathname: string };
}

type LoginTab = "password" | "feishu";

/** 登录页：账号密码 / 飞书扫码。视觉对齐原型 login.html。 */
export function LoginPage() {
  const { user, initializing, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as LocationState | null)?.from?.pathname ?? "/search";

  const [tab, setTab] = useState<LoginTab>("password");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  return (
    <Stack
      direction={{ xs: "column", md: "row" }}
      spacing={{ xs: 4, md: 8 }}
      sx={{ width: "100%", maxWidth: 1040, alignItems: "center" }}
    >
      {/* 品牌介绍：对齐原型 .login-intro 深蓝面板 */}
      <Box
        sx={{
          flex: 1,
          minWidth: 0,
          bgcolor: "#1248a0",
          color: "#fff",
          borderRadius: "12px",
          p: { xs: 3, sm: 5 },
          display: "flex",
          alignItems: "center",
          gap: { xs: 2.5, sm: 3 },
        }}
      >
        <Box
          sx={{
            width: { xs: 60, sm: 78 },
            height: { xs: 60, sm: 78 },
            flexShrink: 0,
            borderRadius: "12px",
            border: "1px solid rgba(255,255,255,.5)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: { xs: 22, sm: 28 },
            fontWeight: 700,
            letterSpacing: "-0.03em",
          }}
        >
          AE
        </Box>
        <Box sx={{ minWidth: 0 }}>
          <Box
            sx={{
              color: "#d6e4ff",
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: 0.12,
              textTransform: "uppercase",
              mb: 1,
            }}
          >
            Product Knowledge
          </Box>
          <Typography
            component="h1"
            sx={{ color: "#fff", fontSize: { xs: 24, sm: 30 }, fontWeight: 700, lineHeight: 1.35 }}
          >
            AE 内部知识平台
          </Typography>
          <Typography sx={{ color: "#e6efff", fontSize: 14, lineHeight: 1.8, mt: 1.5, maxWidth: 420 }}>
            统一查询产品知识，沉淀文档经验，为问题分析提供可靠依据。
          </Typography>
        </Box>
      </Box>

      {/* 登录卡片：对齐原型 .login-card */}
      <Paper
        variant="outlined"
        sx={{
          width: "100%",
          maxWidth: 430,
          borderRadius: "10px",
          borderColor: "#e1e4e8",
          boxShadow: "0 18px 48px rgba(31,35,41,.1)",
        }}
      >
        <Box sx={{ px: 3.5, pt: 3.5, pb: 2.5 }}>
          <Typography component="h2" sx={{ fontSize: 22, fontWeight: 700 }}>
            欢迎登录
          </Typography>
          <Typography color="text.secondary" variant="body2" sx={{ mt: 0.75, fontSize: 13 }}>
            请选择适合你的登录方式
          </Typography>
        </Box>

        <Tabs
          value={tab}
          onChange={(_event, value: LoginTab) => {
            setTab(value);
            setError(null);
          }}
          sx={{ mx: 3.5, mb: 2.5, borderBottom: 1, borderColor: "divider" }}
        >
          <Tab label="账号密码" value="password" sx={{ flex: 1 }} />
          <Tab label="飞书扫码" value="feishu" sx={{ flex: 1 }} />
        </Tabs>

        <Box sx={{ px: 3.5, pb: 2.5 }}>
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
            // 飞书扫码 Tab：二维码由飞书官方 SDK 生成，扫码后由后端回调建立会话。
            <Stack spacing={2}>
              <FeishuQrLogin />
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
        </Box>
      </Paper>
    </Stack>
  );
}
