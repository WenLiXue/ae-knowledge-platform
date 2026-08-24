import { Box, Stack, Typography } from "@mui/material";
import InboxOutlinedIcon from "@mui/icons-material/InboxOutlined";
import type { ReactNode } from "react";

interface EmptyStateProps {
  title: string;
  description?: string;
  action?: ReactNode;
}

/** 列表/区域空状态占位。 */
export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <Stack spacing={1.5} alignItems="center" sx={{ py: 10, textAlign: "center" }}>
      <Box
        sx={{
          width: 56,
          height: 56,
          borderRadius: "50%",
          bgcolor: "action.hover",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "text.secondary",
        }}
      >
        <InboxOutlinedIcon fontSize="large" />
      </Box>
      <Typography variant="h6">{title}</Typography>
      {description && (
        <Typography color="text.secondary" variant="body2" sx={{ maxWidth: 480 }}>
          {description}
        </Typography>
      )}
      {action}
    </Stack>
  );
}
