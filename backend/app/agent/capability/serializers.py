"""Stable API representations for persisted Agent capabilities."""

from ..db.models.capability import AgentMcpServer, AgentSkill, AgentToolConfig


def tool_dict(row: AgentToolConfig) -> dict:
    return {"name": row.name, "version": row.version, "description": row.description,
            "enabled": row.enabled, "source": row.source}


def skill_dict(row: AgentSkill, *, include_content: bool = False) -> dict:
    result = {"id": str(row.id), "name": row.name, "description": row.description,
              "version": row.version, "enabled": row.enabled, "source": row.source,
              "created_at": row.created_at.isoformat() if row.created_at else None,
              "updated_at": row.updated_at.isoformat() if row.updated_at else None}
    if include_content:
        result["content"] = row.content
    return result


def mcp_dict(row: AgentMcpServer) -> dict:
    return {"id": str(row.id), "name": row.name, "endpoint": row.endpoint,
            "description": row.description, "transport": row.transport,
            "auth_type": row.auth_type, "enabled": row.enabled,
            "status": row.status, "last_error": row.last_error,
            "discovered_tools": row.discovered_tools or [],
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None}
