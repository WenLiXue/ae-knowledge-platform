"""Backward-compatible imports for Agent capability models.

Models are split by lifecycle while this module preserves the historical
import path used by migrations and integrations.
"""

from .agent_mcp import AgentMcpServer
from .agent_skill import AgentSkill
from .agent_tool import AgentToolConfig

__all__ = ["AgentToolConfig", "AgentSkill", "AgentMcpServer"]
