import { Box } from "@mui/material";
import type { ReactNode } from "react";

/** 登录等公开页面布局：全屏浅色背景，内容垂直居中。 */
export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <Box
      sx={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        bgcolor: "background.default",
        px: 2,
        py: 6,
      }}
    >
      {children}
    </Box>
  );
}
