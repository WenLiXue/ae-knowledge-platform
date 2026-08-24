import { Box, Stack, Typography } from "@mui/material";
import ConstructionOutlinedIcon from "@mui/icons-material/ConstructionOutlined";
import { PageHeader } from "../components/PageHeader";

interface PlaceholderPageProps {
  title: string;
  description: string;
}

/** 阶段占位页：路由可访问、主体功能后续实现，视觉与其余页面保持一致。 */
export function PlaceholderPage({ title, description }: PlaceholderPageProps) {
  return (
    <>
      <PageHeader title={title} description={description} />
      <Box
        sx={{
          border: 1,
          borderStyle: "dashed",
          borderColor: "divider",
          borderRadius: 2,
          p: 6,
          textAlign: "center",
          bgcolor: "background.paper",
        }}
      >
        <Stack spacing={1.5} alignItems="center">
          <ConstructionOutlinedIcon sx={{ fontSize: 44, color: "text.disabled" }} />
          <Typography variant="h6">此功能正在开发中</Typography>
          <Typography variant="body2" color="text.secondary">
            原型阶段先开放核心页面，本页面将在后续版本中实现。
          </Typography>
        </Stack>
      </Box>
    </>
  );
}
