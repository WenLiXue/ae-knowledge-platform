import { Navigate, useLocation } from "react-router-dom";
import {
  Box,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import { useAuth } from "../auth/AuthContext";
import { FeishuQrLogin } from "../components/FeishuQrLogin";

interface LocationState {
  from?: { pathname: string };
}

/** 登录页：唯一支持飞书扫码登录。视觉对齐原型 login.html。 */
export function LoginPage() {
  const { user, initializing } = useAuth();
  const location = useLocation();
  const from = (location.state as LocationState | null)?.from?.pathname ?? "/search";
  if (!initializing && user) {
    return <Navigate to={from} replace />;
  }

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
          component="img"
          src="/workbench-icon.svg"
          alt="智能工作台"
          sx={{
            width: { xs: 60, sm: 78 },
            height: { xs: 60, sm: 78 },
            flexShrink: 0,
            borderRadius: "12px",
            bgcolor: "#fff",
            p: 1,
          }}
        />
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
            Intelligent Workbench
          </Box>
          <Typography
            component="h1"
            sx={{ color: "#fff", fontSize: { xs: 24, sm: 30 }, fontWeight: 700, lineHeight: 1.35 }}
          >
            AE 智能工作台
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
            请使用飞书扫码登录
          </Typography>
        </Box>

        <Box sx={{ px: 3.5, pb: 2.5 }}>
          <Stack spacing={2}>
            <FeishuQrLogin />
            <Typography variant="caption" color="text.secondary" textAlign="center">
              系统使用飞书 user_id 识别用户；首次扫码自动创建账号，已存在账号则直接登录。
            </Typography>
          </Stack>

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
