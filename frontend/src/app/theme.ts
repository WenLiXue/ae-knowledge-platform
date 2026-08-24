/**
 * 全局 MUI 主题。
 *
 * 与当前视觉风格保持一致：简洁、浅色、企业后台、蓝色主色、信息密度适中。
 */
import { createTheme } from "@mui/material/styles";

const theme = createTheme({
  palette: {
    primary: { main: "#2563eb", dark: "#1d4ed8", light: "#3b82f6", contrastText: "#ffffff" },
    background: { default: "#f7f9fc", paper: "#ffffff" },
    text: { primary: "#1f2329", secondary: "#646a73" },
    divider: "#ebecef",
    success: { main: "#16a34a" },
    warning: { main: "#d97706" },
    error: { main: "#dc2626" },
    info: { main: "#0284c7" },
  },
  shape: { borderRadius: 10 },
  typography: {
    fontFamily: `Inter, "Noto Sans SC", "Microsoft YaHei", system-ui, sans-serif`,
    h4: { fontWeight: 700 },
    h5: { fontWeight: 700 },
    h6: { fontWeight: 600 },
  },
  components: {
    MuiButton: {
      styleOverrides: {
        root: { textTransform: "none", fontWeight: 600 },
      },
    },
    MuiCard: {
      defaultProps: { variant: "outlined" },
      styleOverrides: {
        root: { borderRadius: 12, boxShadow: "none" },
      },
    },
    MuiChip: {
      defaultProps: { size: "small" },
    },
    MuiTableCell: {
      styleOverrides: {
        head: {
          fontWeight: 600,
          color: "#646a73",
          backgroundColor: "#fafbfc",
        },
      },
    },
    MuiTableRow: {
      styleOverrides: {
        root: {
          "&:last-child td": { borderBottom: 0 },
        },
      },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: { backgroundColor: "#ffffff" },
      },
    },
  },
});

export default theme;
