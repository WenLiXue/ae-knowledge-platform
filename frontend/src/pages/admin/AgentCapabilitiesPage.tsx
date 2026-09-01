import { useCallback, useEffect, useState } from "react";
import {
  Alert, Button, Card, CardContent, Chip, Divider, FormControl, InputLabel,
  MenuItem, Select, Stack, Switch, Table, TableBody, TableCell, TableHead,
  TableRow, Tab, Tabs, TextField, Typography,
} from "@mui/material";
import { getErrorMessage } from "../../api/client";
import {
  createMcpServer, importAgentSkill, listAgentCapabilities, setAgentSkillEnabled,
  setAgentToolEnabled, setMcpServerEnabled,
  type AgentCapabilities,
} from "../../api/agentCapabilities";
import { PageHeader } from "../../components/PageHeader";

export function AgentCapabilitiesPage() {
  const [data, setData] = useState<AgentCapabilities | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [tab, setTab] = useState(0);
  const [mcp, setMcp] = useState({ name: "", endpoint: "", description: "", transport: "STREAMABLE_HTTP", auth_type: "NONE", enabled: false });

  const load = useCallback(async () => {
    try { setData(await listAgentCapabilities()); setError(null); } catch (err) { setError(err); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const run = async (action: () => Promise<unknown>, message: string) => {
    try { await action(); setNotice(message); await load(); }
    catch (err) { setError(err); }
  };

  const importSkill = async (file: File | undefined) => {
    if (!file) return;
    await run(() => importAgentSkill(file), "技能已导入。请确认启用状态后再提供给 Agent。");
  };

  const addMcp = async () => {
    if (!mcp.name.trim() || !mcp.endpoint.trim()) return;
    await run(() => createMcpServer({ ...mcp, name: mcp.name.trim(), endpoint: mcp.endpoint.trim() }), "MCP Server 已保存，默认保持关闭。");
    setMcp({ name: "", endpoint: "", description: "", transport: "STREAMABLE_HTTP", auth_type: "NONE", enabled: false });
  };

  return (
    <Stack spacing={3}>
      <PageHeader title="Agent 能力管理" description="管理员管理内置 Tool、按需加载 Skill 和外部 MCP Server。所有变更只影响后续运行。" />
      {error ? <Alert severity="error">{getErrorMessage(error, "加载能力配置失败。")} </Alert> : null}
      {notice && <Alert severity="success" onClose={() => setNotice(null)}>{notice}</Alert>}
      {data && <>
        <Card>
          <CardContent sx={{ pb: 0 }}>
            <Tabs value={tab} onChange={(_, value) => setTab(value)} variant="fullWidth">
              <Tab label="工具" />
              <Tab label="技能" />
              <Tab label="MCP 服务" />
            </Tabs>
          </CardContent>
        </Card>

        {tab === 0 && (
          <Card><CardContent>
            <Typography variant="h6" gutterBottom>内置工具</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>工具由运行时统一加载；关闭后不会进入后续会话的能力集合。</Typography>
            <Table size="small"><TableHead><TableRow><TableCell>名称</TableCell><TableCell>说明</TableCell><TableCell>来源</TableCell><TableCell>状态</TableCell></TableRow></TableHead><TableBody>
              {data.tools.map((item) => <TableRow key={item.name}><TableCell sx={{ width: 220, whiteSpace: "nowrap" }}><Typography sx={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace", fontSize: 14, letterSpacing: 0 }}>{item.name}</Typography></TableCell><TableCell>{item.description}</TableCell><TableCell>{item.source}</TableCell><TableCell><Switch checked={item.enabled} onChange={() => void run(() => setAgentToolEnabled(item.name, !item.enabled), `${item.name} 已${item.enabled ? "停用" : "启用"}。`)} /></TableCell></TableRow>)}
            </TableBody></Table>
          </CardContent></Card>
        )}

        {tab === 1 && (
          <Card><CardContent>
            <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems={{ sm: "center" }} spacing={1}>
              <BoxTitle title="Skills" text="Skill 首先只提供 name/description；Agent 选择匹配后才加载完整 SKILL.md。" />
              <Button component="label" variant="outlined">导入 SKILL.md<input hidden type="file" accept=".md,text/markdown" onChange={(event) => { void importSkill(event.target.files?.[0]); event.currentTarget.value = ""; }} /></Button>
            </Stack>
            <Divider sx={{ my: 2 }} />
            {data.skills.length === 0 ? <Typography color="text.secondary">暂无导入技能。</Typography> : <Table size="small"><TableHead><TableRow><TableCell>名称</TableCell><TableCell>说明</TableCell><TableCell>版本</TableCell><TableCell>状态</TableCell></TableRow></TableHead><TableBody>{data.skills.map((item) => <TableRow key={item.id}><TableCell><Typography fontFamily="monospace">{item.name}</Typography></TableCell><TableCell>{item.description}</TableCell><TableCell>{item.version}</TableCell><TableCell><Switch checked={item.enabled} onChange={() => void run(() => setAgentSkillEnabled(item.id, !item.enabled), `${item.name} 已${item.enabled ? "停用" : "启用"}。`)} /></TableCell></TableRow>)}</TableBody></Table>}
          </CardContent></Card>
        )}

        {tab === 2 && (
          <Card><CardContent>
            <Typography variant="h6" gutterBottom>MCP 服务</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>MCP 服务默认关闭；启用后才会发现并加载其工具，调用仍受权限和白名单控制。</Typography>
            <Stack direction={{ xs: "column", md: "row" }} spacing={1} sx={{ mb: 2 }}><TextField label="名称" size="small" value={mcp.name} onChange={(e) => setMcp({ ...mcp, name: e.target.value })} /><TextField label="Endpoint" size="small" fullWidth value={mcp.endpoint} onChange={(e) => setMcp({ ...mcp, endpoint: e.target.value })} /><FormControl size="small" sx={{ minWidth: 150 }}><InputLabel>认证</InputLabel><Select label="认证" value={mcp.auth_type} onChange={(e) => setMcp({ ...mcp, auth_type: e.target.value })}><MenuItem value="NONE">无</MenuItem><MenuItem value="OAUTH2">OAuth 2</MenuItem><MenuItem value="BEARER">Bearer</MenuItem></Select></FormControl><Button variant="contained" onClick={() => void addMcp()}>添加</Button></Stack>
            {data.mcp_servers.length === 0 ? <Typography color="text.secondary">暂无 MCP Server。</Typography> : <Table size="small"><TableHead><TableRow><TableCell>名称</TableCell><TableCell>Endpoint</TableCell><TableCell>传输</TableCell><TableCell>状态</TableCell><TableCell>启用</TableCell></TableRow></TableHead><TableBody>{data.mcp_servers.map((item) => <TableRow key={item.id}><TableCell>{item.name}</TableCell><TableCell>{item.endpoint}</TableCell><TableCell>{item.transport}</TableCell><TableCell><Chip size="small" label={item.status} /></TableCell><TableCell><Switch checked={item.enabled} onChange={() => void run(() => setMcpServerEnabled(item.id, !item.enabled), `${item.name} 已${item.enabled ? "停用" : "启用"}。`)} /></TableCell></TableRow>)}</TableBody></Table>}
          </CardContent></Card>
        )}
      </>}
    </Stack>
  );
}

function BoxTitle({ title, text }: { title: string; text: string }) {
  return <Stack><Typography variant="h6">{title}</Typography><Typography variant="body2" color="text.secondary">{text}</Typography></Stack>;
}
