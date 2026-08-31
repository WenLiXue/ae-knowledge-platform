import { useEffect, useState } from "react";
import { Alert, Button, Card, CardContent, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Table, TableBody, TableCell, TableHead, TableRow } from "@mui/material";
import { getAdminUser, listAdminUsers, type AdminUser, type AdminUserDetail } from "../../api/adminUsers";
import { ListPagination } from "../../components/ListPagination";
import { PageHeader } from "../../components/PageHeader";

export function UsersPage() {
  const [items, setItems] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [error, setError] = useState<unknown>(null);
  const [detail, setDetail] = useState<AdminUserDetail | null>(null);
  const load = (p = page, size = pageSize) => listAdminUsers({ limit: size, offset: (p - 1) * size }).then(d => { setItems(d.items); setTotal(d.total); setPage(p); }).catch(setError);
  useEffect(() => { void load(1); }, []);
  return <><PageHeader title="用户管理" description="查看用户、角色与账号状态。" actions={<Button variant="outlined" onClick={() => void load()}>刷新</Button>} />{error && <Alert severity="error">加载用户失败</Alert>}<Card><CardContent><Table size="small"><TableHead><TableRow><TableCell>用户</TableCell><TableCell>飞书账号 ID</TableCell><TableCell>角色</TableCell><TableCell>状态</TableCell></TableRow></TableHead><TableBody>{items.map(u => <TableRow key={u.id} hover onClick={() => void getAdminUser(u.id).then(setDetail).catch(setError)} sx={{ cursor: "pointer" }}><TableCell>{u.display_name}</TableCell><TableCell>{u.username || "—"}</TableCell><TableCell>{u.is_admin ? <Chip size="small" label="管理员" color="primary" /> : "普通用户"}</TableCell><TableCell>{u.status === "ACTIVE" ? "正常" : "已禁用"}</TableCell></TableRow>)}</TableBody></Table></CardContent><ListPagination page={page} pageSize={pageSize} total={total} onPageChange={p => void load(p)} onPageSizeChange={s => { setPageSize(s); void load(1, s); }} /></Card><Dialog open={Boolean(detail)} onClose={() => setDetail(null)}><DialogTitle>用户详情</DialogTitle><DialogContent>{detail && <>姓名：{detail.display_name}<br />飞书账号 ID：{detail.username || "—"}<br />角色：{detail.is_admin ? "管理员" : "普通用户"}<br />状态：{detail.status === "ACTIVE" ? "正常" : "已禁用"}<br />飞书绑定：{detail.feishu.bound ? "已绑定" : "未绑定"}</>}</DialogContent><DialogActions><Button onClick={() => setDetail(null)}>关闭</Button></DialogActions></Dialog></>;
}
