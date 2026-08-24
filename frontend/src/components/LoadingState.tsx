import { Box, CircularProgress, Typography } from "@mui/material";

/** 内容区加载占位。 */
export function LoadingState({ label = "加载中…" }: { label?: string }) {
  return (
    <Box
      sx={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 1.5,
        py: 10,
      }}
    >
      <CircularProgress size={28} />
      <Typography color="text.secondary" variant="body2">
        {label}
      </Typography>
    </Box>
  );
}

/** 整页加载占位（路由鉴权恢复会话时使用）。 */
export function FullPageLoading({ label = "正在加载…" }: { label?: string }) {
  return (
    <Box
      sx={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "100vh",
        gap: 1.5,
      }}
    >
      <CircularProgress size={32} />
      <Typography color="text.secondary" variant="body2">
        {label}
      </Typography>
    </Box>
  );
}
