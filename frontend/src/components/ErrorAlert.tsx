import { Alert, Button } from "@mui/material";
import { getErrorMessage } from "../api/client";

interface ErrorAlertProps {
  error: unknown;
  onRetry?: () => void;
  title?: string;
}

/** 统一错误提示；error 会经 getErrorMessage 转换为用户可读文案。 */
export function ErrorAlert({ error, onRetry, title }: ErrorAlertProps) {
  return (
    <Alert
      severity="error"
      sx={{ mb: 2 }}
      action={
        onRetry ? (
          <Button color="inherit" size="small" onClick={onRetry}>
            重试
          </Button>
        ) : undefined
      }
    >
      {title && <strong>{title}：</strong>}
      {getErrorMessage(error)}
    </Alert>
  );
}
