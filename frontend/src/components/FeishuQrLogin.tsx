import { useEffect, useRef, useState } from "react";
import { Alert, Box, Button, CircularProgress, Stack, Typography } from "@mui/material";
import { feishuLoginStart } from "../api/auth";
import { getErrorMessage } from "../api/client";

type QrLoginObject = {
  matchOrigin: (origin: string) => boolean;
};

type QrLoginFactory = (options: { id: string; goto: string; style: string }) => QrLoginObject;

declare global {
  interface Window {
    QRLogin?: QrLoginFactory;
  }
}

const CONTAINER_ID = "feishu-qr-login-container";

/** 飞书官方 QRLogin SDK 的 React 封装；扫码结果通过 postMessage 返回临时码。 */
export function FeishuQrLogin() {
  const [state, setState] = useState<"loading" | "ready" | "waiting" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const handledCode = useRef<string | null>(null);
  const authorizeUrlRef = useRef<string | null>(null);

  useEffect(() => {
    let active = true;
    let qrLogin: QrLoginObject | undefined;

    const handleMessage = (event: MessageEvent) => {
      if (!qrLogin || !qrLogin.matchOrigin(event.origin)) return;
      const temporaryCode = typeof event.data === "string" ? event.data : "";
      if (!temporaryCode || handledCode.current === temporaryCode) return;
      handledCode.current = temporaryCode;
      setState("waiting");
      const authUrl = authorizeUrlRef.current;
      if (!authUrl) return;
      const separator = authUrl.includes("?") ? "&" : "?";
      window.location.assign(`${authUrl}${separator}tmp_code=${encodeURIComponent(temporaryCode)}`);
    };

    const initialize = async () => {
      try {
        const { auth_url: authUrl } = await feishuLoginStart();
        if (!active) return;
        if (!window.QRLogin) {
          throw new Error("飞书扫码组件尚未加载，请刷新页面后重试。");
        }
        if (!authUrl.startsWith("http")) {
          throw new Error("飞书扫码登录服务尚未配置，请联系管理员。");
        }
        authorizeUrlRef.current = authUrl;

        qrLogin = window.QRLogin({
          id: CONTAINER_ID,
          goto: authUrl,
          style: "width: 280px; height: 280px; border: 0; background-color: #f5f8ff;",
        });
        window.addEventListener("message", handleMessage);
        setState("ready");
      } catch (reason) {
        if (active) {
          setError(getErrorMessage(reason, "二维码加载失败，请重试。"));
          setState("error");
        }
      }
    };

    void initialize();
    return () => {
      active = false;
      window.removeEventListener("message", handleMessage);
      const container = document.getElementById(CONTAINER_ID);
      if (container) container.replaceChildren();
    };
  }, [refreshKey]);

  return (
    <Stack spacing={2} alignItems="center">
      <Box
        sx={{
          width: 300,
          height: 300,
          display: "grid",
          placeItems: "center",
          border: 1,
          borderColor: "divider",
          borderRadius: 2,
          bgcolor: "#f5f8ff",
          overflow: "hidden",
        }}
      >
        <Box id={CONTAINER_ID} aria-label="飞书扫码区域" />
        {state === "loading" && <CircularProgress size={28} />}
      </Box>
      {state === "ready" && (
        <Typography variant="body2" color="text.secondary" textAlign="center">
          使用飞书移动端扫描二维码，在手机上确认登录
        </Typography>
      )}
      {state === "waiting" && <Alert severity="info">已收到扫码，请等待登录确认…</Alert>}
      {state === "error" && (
        <Stack spacing={1.5} alignItems="center" sx={{ width: "100%" }}>
          <Alert severity="warning" sx={{ width: "100%" }}>{error}</Alert>
          <Button variant="outlined" onClick={() => { handledCode.current = null; setError(null); setState("loading"); setRefreshKey((key) => key + 1); }}>
            刷新二维码
          </Button>
        </Stack>
      )}
    </Stack>
  );
}
