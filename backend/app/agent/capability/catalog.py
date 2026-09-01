"""Database-backed enablement catalog for Agent capabilities."""

from __future__ import annotations

from sqlalchemy import select

from ...db.models.capability import AgentSkill, AgentToolConfig


def enabled_tool_names(db) -> set[str]:
    return set(db.execute(select(AgentToolConfig.name).where(AgentToolConfig.enabled.is_(True))).scalars())


def enabled_skills(db) -> list[AgentSkill]:
    return list(db.execute(select(AgentSkill).where(AgentSkill.enabled.is_(True)).order_by(AgentSkill.name)).scalars())


def skill_catalog(db) -> list[dict]:
    return [{"name": s.name, "description": s.description, "version": s.version} for s in enabled_skills(db)]
