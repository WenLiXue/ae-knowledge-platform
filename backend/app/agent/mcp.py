"""Backward-compatible MCP facade.

New code should import from ``mcp_client``, ``mcp_tools`` and ``mcp_loader``
according to responsibility. This module remains for existing integrations.
"""

from .mcp_client import McpDiscoveryError, discover as discover_tools, rpc
from .mcp_loader import register_discovered_tools
from .mcp_tools import McpArguments, McpRemoteTool

__all__ = [
    "McpArguments", "McpDiscoveryError", "McpRemoteTool",
    "discover_tools", "register_discovered_tools",
]

# Private compatibility alias retained for integrations that used the old
# module while the MCP implementation lived in one file.
_rpc = rpc
