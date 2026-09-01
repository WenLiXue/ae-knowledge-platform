"""Load enabled, previously discovered MCP tools into a registry."""

from .mcp_tools import McpRemoteTool


def register_discovered_tools(registry, db) -> None:
    from ..db.models.capability import AgentMcpServer

    for server in db.query(AgentMcpServer).filter(AgentMcpServer.enabled.is_(True)).all():
        for item in server.discovered_tools or []:
            try:
                registry.register(McpRemoteTool(server.endpoint, server.name, item))
            except (KeyError, ValueError):
                continue
