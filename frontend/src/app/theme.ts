import { alpha, createTheme } from "@mui/material/styles";

/**
 * 设计 token：全部抽取自 docs/prototypes/visual-directions/styles.css，
 * 保持前端与 HTML 原型视觉一致（浅灰画布、白色卡片、蓝色主操作、语义状态标签）。
 */
const P = {
  canvas: "#f3f5f8", // 页面画布 --surface-soft
  loginCanvas: "#eef2f6", // 登录页画布
  surface: "#ffffff", // 卡片 --surface
  ink: "#1f2329", // 主文字 --ink
  muted: "#646a73", // 次级文字 --muted
  faint: "#8c8c8c", // 弱化文字 --faint
  line: "#ebecef", // 默认边框 --line
  lineStrong: "#d9d9d9", // 输入框/强边框 --line-strong
  rowLine: "#f0f0f0", // 表格行分隔
  tableHead: "#fafafa", // 表头底
  blue: "#0958d9", // 主操作 --blue
  blueDark: "#003eb3", // hover --blue-dark
  blueFocus: "#1677ff", // focus / 进度条
  blueSoft: "#69b1ff", // 输入 hover 边框
  blueLine: "#91caff", // 选中浅边框
  blueTint: "#e6f4ff", // 主色浅底 --surface-blue
  blueTintSoft: "#f7faff", // 更浅底
  success: "#237804", // 成功文字（绿底 #f6ffed）
  successDot: "#52c41a", // 成功圆点
  warning: "#d48806", // 警示文字（黄底 #fffbe6）
  warningText: "#874d00", // 警示强调文字
  warningBorder: "#ffe58f", // 警示边框
  error: "#cf1322", // 失败文字（红底 #fff2f0）
  errorBorder: "#ffccc7", // 失败边框
  neutral: "#f2f3f5", // 中性标签底
  tagText: "#3c4043", // 中性标签文字
  disabled: "#bfbfbf", // 禁用文字
  disabledBg: "#f5f5f5", // 禁用底
} as const;

const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: P.blue, dark: P.blueDark, light: P.blueSoft, contrastText: "#ffffff" },
    secondary: { main: P.muted },
    background: { default: P.canvas, paper: P.surface },
    text: { primary: P.ink, secondary: P.muted, disabled: P.faint },
    divider: P.line,
    success: { main: P.success, dark: "#1a5c03", light: "#f6ffed", contrastText: "#ffffff" },
    warning: { main: P.warning, dark: P.warningText, light: "#fffbe6", contrastText: "#ffffff" },
    error: { main: P.error, dark: "#a8071a", light: "#fff2f0", contrastText: "#ffffff" },
    info: { main: P.blueFocus, dark: P.blue, light: P.blueTint, contrastText: "#ffffff" },
    action: {
      hover: alpha(P.blue, 0.06),
      hoverOpacity: 0.06,
      selected: P.blueTint,
      focus: alpha(P.blueFocus, 0.12),
    },
  },
  shape: { borderRadius: 8 },
  typography: {
    fontFamily: `Inter, "Noto Sans SC", "Microsoft YaHei", system-ui, sans-serif`,
    fontSize: 14,
    h4: { fontSize: 28, fontWeight: 700, lineHeight: 1.3, letterSpacing: "-0.02em" },
    h5: { fontSize: 22, fontWeight: 700, lineHeight: 1.35, letterSpacing: "-0.02em" },
    h6: { fontSize: 17, fontWeight: 600, lineHeight: 1.4 },
    subtitle1: { fontSize: 15, fontWeight: 600, lineHeight: 1.5 },
    subtitle2: { fontSize: 14, fontWeight: 600, lineHeight: 1.5 },
    body1: { fontSize: 15, lineHeight: 1.6 },
    body2: { fontSize: 13, lineHeight: 1.6 },
    caption: { fontSize: 12, lineHeight: 1.5 },
    overline: { fontSize: 12, fontWeight: 600, letterSpacing: 0.04 },
    button: { textTransform: "none", fontWeight: 600 },
  },
  components: {
    // 按钮：原型 .ae-button / .btn —— 白底描边为默认，主蓝为 primary
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: 6,
          minHeight: 36,
          padding: "0 15px",
          fontWeight: 600,
          boxShadow: "none",
        },
        contained: {
          backgroundColor: P.blue,
          border: `1px solid ${P.blue}`,
          "&:hover": { backgroundColor: P.blueDark, borderColor: P.blueDark, boxShadow: "none" },
          "&:disabled": { color: P.disabled, backgroundColor: P.disabledBg, borderColor: P.lineStrong },
        },
        outlined: {
          color: P.ink,
          borderColor: P.lineStrong,
          "&:hover": {
            color: P.blue,
            borderColor: P.blueSoft,
            backgroundColor: "transparent",
            boxShadow: "none",
          },
          "&:disabled": { color: P.disabled, borderColor: P.lineStrong, backgroundColor: P.disabledBg },
        },
        text: {
          color: P.blue,
          "&:hover": { backgroundColor: P.blueTint },
        },
        sizeSmall: { minHeight: 30, padding: "0 10px", fontSize: 13 },
        sizeLarge: { minHeight: 42, padding: "0 18px", fontSize: 15 },
      },
    },
    // 卡片：白色 + 1px 边框 + 8px 圆角
    MuiCard: {
      defaultProps: { variant: "outlined" },
      styleOverrides: {
        root: { borderRadius: 8, boxShadow: "none", border: `1px solid ${P.line}` },
      },
    },
    MuiPaper: {
      styleOverrides: { outlined: { borderColor: P.line } },
    },
    // 输入框 / 下拉：1px #d9d9d9，hover 变 #69b1ff，focus 蓝色描边 + 浅蓝光环
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          backgroundColor: "#ffffff",
          borderRadius: 6,
          "& .MuiOutlinedInput-notchedOutline": { borderColor: P.lineStrong },
          "&:hover .MuiOutlinedInput-notchedOutline": { borderColor: P.blueSoft },
          "&.Mui-focused .MuiOutlinedInput-notchedOutline": {
            borderColor: P.blueFocus,
            borderWidth: 1,
            boxShadow: `0 0 0 2px ${alpha(P.blueFocus, 0.12)}`,
          },
        },
      },
    },
    // 表格：表头 #fafafa + 600 权重，行分隔 #f0f0f0，hover 浅蓝底
    MuiTableCell: {
      styleOverrides: {
        root: { fontSize: 13, padding: "10px 14px", borderBottom: `1px solid ${P.rowLine}` },
        head: {
          fontWeight: 600,
          color: P.ink,
          backgroundColor: P.tableHead,
          borderBottom: `1px solid ${P.line}`,
        },
      },
    },
    MuiTableRow: {
      styleOverrides: {
        root: { "&:hover": { backgroundColor: P.blueTintSoft } },
      },
    },
    // 标签 Chip：24px 高、4px 圆角；仅默认色（无 color）走中性灰底，带 color 的保留语义色
    MuiChip: {
      styleOverrides: {
        root: {
          height: 24,
          fontSize: 12,
          borderRadius: 4,
        },
        colorDefault: { backgroundColor: P.neutral, color: P.muted },
        outlined: { borderColor: P.lineStrong, backgroundColor: "transparent", color: P.ink },
        label: { paddingLeft: 8, paddingRight: 8 },
      },
    },
    // Tabs：3px 蓝色下划线（登录页 / 分类页）
    MuiTabs: {
      styleOverrides: {
        indicator: { backgroundColor: P.blue, height: 3, borderRadius: "3px 3px 0 0" },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: {
          textTransform: "none",
          minHeight: 46,
          fontSize: 14,
          color: P.muted,
          fontWeight: 500,
          "&.Mui-selected": { color: P.blue, fontWeight: 600 },
        },
      },
    },
    // Alert：对齐原型语义底色
    MuiAlert: {
      styleOverrides: {
        root: { borderRadius: 7, fontSize: 13 },
        standardSuccess: {
          backgroundColor: "#f6ffed",
          color: P.success,
          "& .MuiAlert-icon": { color: P.success },
        },
        standardInfo: {
          backgroundColor: P.blueTint,
          color: P.blue,
          "& .MuiAlert-icon": { color: P.blue },
        },
        standardWarning: {
          backgroundColor: "#fffbe6",
          color: P.warningText,
          "& .MuiAlert-icon": { color: P.warning },
        },
        standardError: {
          backgroundColor: "#fff2f0",
          color: P.error,
          "& .MuiAlert-icon": { color: P.error },
        },
      },
    },
    MuiAppBar: { styleOverrides: { root: { boxShadow: "none" } } },
    MuiToolbar: { styleOverrides: { root: { minHeight: 56 } } },
    MuiDivider: { styleOverrides: { root: { borderColor: P.line } } },
    // 侧边导航选中态：原型 .session.active / .product-config-item.active 的浅蓝 tint
    MuiListItemButton: {
      styleOverrides: {
        root: {
          borderRadius: 6,
          "&.Mui-selected": {
            backgroundColor: P.blueTint,
            color: P.blue,
            "&:hover": { backgroundColor: P.blueTint },
          },
        },
      },
    },
  },
});

export default theme;
