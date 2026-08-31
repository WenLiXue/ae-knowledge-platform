import { useEffect, useState } from "react";
import { Alert, Button, Card, CardContent, Chip, Table, TableBody, TableCell, TableHead, TableRow, Typography } from "@mui/material";
import { getErrorMessage } from "../../api/client";
import { listAdminUsers, updateAdminUser, type AdminUser } from "../../api/adminUsers";
import { PageHeader } from "../../components/PageHeader";

export function UsersPage() {
  const [items, setItems] = useState<AdminUser[]>([]); const [error, setError] = useState<unknown>(null);
  const load = () => listAdminUsers().then(d => setItems(d.items)).catch(setError);
  useEffect(() => { void load(); }, []);
  const toggle = async (u: AdminUser) => { try { const next = await updateAdminUser(u.id, { status: u.status === "ACTIVE" ? "DISABLED" : "ACTIVE" }); setItems(xs => xs.map(x => x.id === u.id ? next : x)); } catch (e) { setError(e); } };
  return <><PageHeader title="用户管理" description="查看用户、角色与账号状态。管理员可启用或禁用账号。" actions={<Button variant="outlined" onClick={load}>刷新</Button>} />{error && <Alert severity="error" sx={{ mb: 2 }}>{getErrorMessage(error)}</Alert>}<Card><CardContent><Table size="small"><TableHead><TableRow><TableCell>用户</TableCell><TableCell>账号</TableCell><TableCell>角色</TableCell><TableCell>状态</TableCell><TableCell>操作</TableCell></TableRow></TableHead><TableBody>{items.map(u => <TableRow key={u.id}><TableCell><Typography fontWeight={600}>{u.display_name}</Typography><Typography variant="caption" color="text.secondary">{u.email || "—"}</Typography></TableCell><TableCell>{u.username || "—"}</TableCell><TableCell>{u.is_admin ? <Chip size="small" label="管理员" color="primary" /> : "普通用户"}</TableCell><TableCell><Chip size="small" label={u.status === "ACTIVE" ? "正常" : "已禁用"} color={u.status === "ACTIVE" ? "success" : "default"} /></TableCell><TableCell><Button size="small" color={u.status === "ACTIVE" ? "error" : "primary"} onClick={() => void toggle(u)}>{u.status === "ACTIVE" ? "禁用" : "启用"}</Button></TableCell></TableRow>)}</TableBody></Table></CardContent></Card></>;
}
