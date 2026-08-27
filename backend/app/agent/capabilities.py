"""Capability discovery and validation shared by admin APIs and Agent runtime."""

from __future__ import annotations

import re

from sqlalchemy import select

from ..db.models.capability import AgentSkill, AgentToolConfig

SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
MAX_SKILL_BYTES = 10 * 1024 * 1024


def enabled_tool_names(db) -> set[str]:
    return set(db.execute(select(AgentToolConfig.name).where(AgentToolConfig.enabled.is_(True))).scalars())


def enabled_skills(db) -> list[AgentSkill]:
    return list(db.execute(select(AgentSkill).where(AgentSkill.enabled.is_(True)).order_by(AgentSkill.name)).scalars())


def parse_skill_document(content: str) -> tuple[str, str]:
    if not content or len(content.encode("utf-8")) > MAX_SKILL_BYTES:
        raise ValueError("技能文件为空或超过 10MB")
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md 必须以 YAML frontmatter 开始")
    try:
        end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise ValueError("SKILL.md 缺少 frontmatter 结束标记") from exc
    values: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip('"\'')
    name = values.get("name", "")
    description = values.get("description", "")
    if not SKILL_NAME_RE.fullmatch(name):
        raise ValueError("技能 name 只能包含小写字母、数字、点、下划线和短横线")
    if not description or len(description) > 1024:
        raise ValueError("技能 description 不能为空且不能超过 1024 字符")
    return name, description


def skill_catalog(db) -> list[dict]:
    return [
        {"name": s.name, "description": s.description, "version": s.version}
        for s in enabled_skills(db)
    ]
