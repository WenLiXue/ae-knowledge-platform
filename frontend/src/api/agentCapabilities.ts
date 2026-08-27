import { apiGet, apiPatch, apiPost } from "./client";

export interface AgentToolConfig {
  name: string;
  version: string;
  description: string;
  enabled: boolean;
  source: string;
}

export interface AgentSkill {
  id: string;
  name: string;
  description: string;
  version: string;
  enabled: boolean;
  source: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface AgentMcpServer {
  id: string;
  name: string;
  endpoint: string;
  description: string;
  transport: string;
  auth_type: string;
  enabled: boolean;
  status: string;
  last_error: string | null;
  discovered_tools: Array<{ name?: string; description?: string }>;
  created_at: string | null;
  updated_at: string | null;
}

export interface AgentCapabilities {
  tools: AgentToolConfig[];
  skills: AgentSkill[];
  mcp_servers: AgentMcpServer[];
}

export function listAgentCapabilities(): Promise<AgentCapabilities> {
  return apiGet<AgentCapabilities>("/api/v1/admin/agent/capabilities");
}

export function setAgentToolEnabled(name: string, enabled: boolean): Promise<AgentToolConfig> {
  return apiPatch<AgentToolConfig>(`/api/v1/admin/agent/tools/${encodeURIComponent(name)}`, { enabled });
}

export function setAgentSkillEnabled(id: string, enabled: boolean): Promise<AgentSkill> {
  return apiPatch<AgentSkill>(`/api/v1/admin/agent/skills/${id}`, { enabled });
}

export function importAgentSkill(file: File): Promise<AgentSkill> {
  const form = new FormData();
  form.append("file", file);
  return apiPost<AgentSkill>("/api/v1/admin/agent/skills/import", form);
}

export function createMcpServer(payload: {
  name: string;
  endpoint: string;
  description: string;
  transport: string;
  auth_type: string;
  enabled: boolean;
}): Promise<AgentMcpServer> {
  return apiPost<AgentMcpServer>("/api/v1/admin/agent/mcp-servers", payload);
}

export function setMcpServerEnabled(id: string, enabled: boolean): Promise<AgentMcpServer> {
  return apiPatch<AgentMcpServer>(`/api/v1/admin/agent/mcp-servers/${id}`, { enabled });
}
