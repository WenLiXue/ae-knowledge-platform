import { useState } from "react";
import { Alert, Button, Stack, Typography } from "@mui/material";
import QrCode2Icon from "@mui/icons-material/QrCode2";
import { feishuLoginStart } from "../api/auth";
import { getErrorMessage } from "../api/client";

/**
 * 飞书扫码登录（直连方式）。
 *
 * 嵌入式 QRLogin SDK 在部分环境下 postMessage 不稳定；这里改为点击后直接
 * 跳转飞书 passport 扫码页，扫码 → 回调后端 → 绑定 → 跳回前端。
 */
export function FeishuQrLogin() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleStart = async () => {
    setLoading(true);
    setError(null);
    try {
      const { auth_url: authUrl } = await feishuLoginStart();
      if (!authUrl.startsWith("http")) {
        throw new Error("飞书扫码登录服务尚未配置，请联系管理员。");
      }
      // 直接跳转飞书授权页（浏览器整页跳转，不经过 SDK postMessage）
      window.location.href = authUrl;
    } catch (reason) {
      setError(getErrorMessage(reason, "获取飞书登录地址失败，请重试。"));
      setLoading(false);
    }
  };

  return (
    <Stack spacing={2} alignItems="center">
      <Button
        variant="outlined"
        size="large"
        startIcon={<QrCode2Icon />}
        onClick={handleStart}
        disabled={loading}
        sx={{ width: 280 }}
      >
        {loading ? "跳转中…" : "使用飞书扫码登录"}
      </Button>
      {error && <Alert severity="warning">{error}</Alert>}
      <Typography variant="body2" color="text.secondary" textAlign="center">
        点击后将跳转到飞书，使用飞书 App 扫码并确认登录
      </Typography>
    </Stack>
  );
}
