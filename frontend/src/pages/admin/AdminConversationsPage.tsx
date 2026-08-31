import { useEffect, useState } from "react";
import { Alert, Box, Card, CardContent, Divider, List, ListItemButton, Stack, Typography } from "@mui/material";
import { getAdminConversation, listAdminConversations, type AdminConversation } from "../../api/adminUsers";
import { getErrorMessage } from "../../api/client";
import { PageHeader } from "../../components/PageHeader";

export function AdminConversationsPage() {
  const [items, setItems] = useState<AdminConversation[]>([]); const [selected, setSelected] = useState<Awaited<ReturnType<typeof getAdminConversation>> | null>(null); const [error, setError] = useState<unknown>(null);
  useEffect(() => { void listAdminConversations().then(d => setItems(d.items)).catch(setError); }, []);
  const open = (id: string) => void getAdminConversation(id).then(setSelected).catch(setError);
  return <><PageHeader title="全部会话" description="管理员只读查看所有用户的对话记录；此页面不提供提问、重试或反馈操作。" />{error && <Alert severity="error">{getErrorMessage(error)}</Alert>}<Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ alignItems: "stretch" }}><Card sx={{ width: { md: 360 }, flexShrink: 0 }}><List>{items.map(c => <ListItemButton key={c.id} selected={selected?.conversation.id === c.id} onClick={() => open(c.id)}><Box sx={{ minWidth: 0 }}><Typography noWrap fontWeight={600}>{c.title}</Typography><Typography variant="caption" color="text.secondary">{c.owner.display_name} · {c.owner.username || "无账号"}</Typography></Box></ListItemButton>)}</List></Card><Card sx={{ flex: 1, minHeight: 480 }}><CardContent>{!selected ? <Typography color="text.secondary">选择一个会话查看记录</Typography> : <><Typography variant="h6">{selected.conversation.title}</Typography><Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>所属用户：{selected.conversation.owner.display_name}（只读）</Typography><Divider />{selected.messages.map(m => <Box key={m.id} sx={{ py: 1.5 }}><Typography variant="caption" color="text.secondary">{m.role === "user" ? "用户" : "知识助手"}</Typography><Typography sx={{ whiteSpace: "pre-wrap" }}>{m.content || m.answer?.summary || "（处理中）"}</Typography></Box>)}</>}</CardContent></Card></Stack></>;
}
