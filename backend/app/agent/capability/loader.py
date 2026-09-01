"""Load administrator capability switches into a run without owning execution."""

from __future__ import annotations

import uuid

from .catalog import enabled_skills, enabled_tool_names
from ..mcp_loader import register_discovered_tools
from ...db.models.user import User


def load_enabled_capabilities(db, registry, *, user_id: str | None = None):
    """Apply persisted enablement to a code-owned registry.

    Tool definitions remain owned by code; the database only controls which
    built-ins and MCP servers are enabled for the current run.
    """
    principal = None
    if user_id:
        user = db.get(User, uuid.UUID(str(user_id)))
        if user is not None:
            principal = user

    configured = enabled_tool_names(db)
    register_discovered_tools(registry, db)
    if configured:
        for name in tuple(registry.names()):
            if not name.startswith("mcp.") and name not in configured:
                registry.remove(name)
    skills = tuple(
        {"name": item.name, "description": item.description, "version": item.version}
        for item in enabled_skills(db)
    )
    return principal, skills
