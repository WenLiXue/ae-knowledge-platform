import { useEffect, useState } from "react";
import { Alert, Avatar, Button, Card, CardContent, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography } from "@mui/material";
import { getAdminUser, listAdminUsers, updateAdminUser, type AdminUser, type AdminUserDetail } from "../../api/adminUsers";
import { useAuth } from "../../auth/AuthContext";
import { ListPagination } from "../../components/ListPagination";
import { PageHeader } from "../../components/PageHeader";

function formatDate(value: string | null | undefined): string {
  if (!value) return "未提供";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

function DetailField({ label, value }: { label: string; value: string | null | undefined }) {
  return <Stack direction="row" spacing={2} sx={{ py: 0.75, borderBottom: 1, borderColor: "divider" }}><Typography variant="body2" color="text.secondary" sx={{ width: 112, flexShrink: 0 }}>{label}</Typography><Typography variant="body2" sx={{ wordBreak: "break-all" }}>{value || "未提供"}</Typography></Stack>;
}

export function UsersPage() {
  const { user: currentUser } = useAuth();
  const [items, setItems] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [error, setError] = useState<unknown>(null);
  const [detail, setDetail] = useState<AdminUserDetail | null>(null);
  const load = (p = page, size = pageSize) => listAdminUsers({ limit: size, offset: (p - 1) * size }).then(d => { setItems(d.items); setTotal(d.total); setPage(p); }).catch(setError);
  useEffect(() => { void load(1); }, []);
  const toggle = async (u: AdminUser) => { try { const next = await updateAdminUser(u.id, { status: u.status === "ACTIVE" ? "DISABLED" : "ACTIVE" }); setItems(xs => xs.map(x => x.id === u.id ? { ...next, avatar_url: next.avatar_url ?? u.avatar_url } : x)); } catch (err) { setError(err); } };
  return <><PageHeader title="用户管理" description="查看用户、角色与账号状态。" actions={<Button variant="outlined" onClick={() => void load()}>刷新</Button>} />{error && <Alert severity="error">加载用户失败</Alert>}<Card><CardContent><Table size="small"><TableHead><TableRow><TableCell>用户</TableCell><TableCell>飞书账号 ID</TableCell><TableCell>角色</TableCell><TableCell>状态</TableCell><TableCell>操作</TableCell></TableRow></TableHead><TableBody>{items.map(u => { const protectedAccount = u.created_source === "SYSTEM" || u.id === currentUser?.id; return <TableRow key={u.id} hover onClick={() => void getAdminUser(u.id).then(setDetail).catch(setError)} sx={{ cursor: "pointer" }}><TableCell><Stack direction="row" spacing={1} alignItems="center"><Avatar src={u.avatar_url || undefined} sx={{ width: 32, height: 32 }}>{u.display_name.slice(0, 1)}</Avatar><span>{u.display_name}</span></Stack></TableCell><TableCell>{u.username || "—"}</TableCell><TableCell>{u.is_admin ? <Chip size="small" label="管理员" color="primary" /> : "普通用户"}</TableCell><TableCell>{u.status === "ACTIVE" ? "正常" : "已禁用"}</TableCell><TableCell onClick={e => e.stopPropagation()}><Button size="small" disabled={protectedAccount} color={u.status === "ACTIVE" ? "error" : "primary"} onClick={() => void toggle(u)}>{protectedAccount ? "不可操作" : u.status === "ACTIVE" ? "禁用" : "启用"}</Button></TableCell></TableRow>; })}</TableBody></Table></CardContent><ListPagination page={page} pageSize={pageSize} total={total} onPageChange={p => void load(p)} onPageSizeChange={s => { setPageSize(s); void load(1, s); }} /></Card><Dialog open={Boolean(detail)} onClose={() => setDetail(null)} maxWidth="sm" fullWidth><DialogTitle>用户详情</DialogTitle><DialogContent>{detail && <Stack spacing={0.25}><Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 1 }}><Avatar src={detail.avatar_url || undefined}>{detail.display_name.slice(0, 1)}</Avatar><Typography variant="subtitle1" fontWeight={700}>{detail.display_name}</Typography></Stack><DetailField label="姓名" value={detail.display_name} /><DetailField label="账号" value={detail.username} /><DetailField label="邮箱" value={detail.email} /><DetailField label="角色" value={detail.is_admin ? "管理员" : "普通用户"} /><DetailField label="状态" value={detail.status === "ACTIVE" ? "正常" : "已禁用"} /><DetailField label="创建来源" value={detail.created_source} /><DetailField label="创建时间" value={formatDate(detail.created_at)} /><DetailField label="飞书绑定" value={detail.feishu.bound ? "已绑定" : "未绑定"} /><DetailField label="飞书租户" value={detail.feishu.tenant_key} /><DetailField label="飞书用户 ID" value={detail.feishu.external_user_id} /><DetailField label="Open ID" value={detail.feishu.open_id} /><DetailField label="Union ID" value={detail.feishu.union_id} /><DetailField label="绑定时间" value={formatDate(detail.feishu.bound_at)} /><DetailField label="授权过期" value={formatDate(detail.feishu.access_expires_at)} /></Stack>}</DialogContent><DialogActions><Button onClick={() => setDetail(null)}>关闭</Button></DialogActions></Dialog></>;
}
