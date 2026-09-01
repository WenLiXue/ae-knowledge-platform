"""Backward-compatible facade for the capability catalog.

Use ``agent.capability.catalog`` and ``agent.capability.skill_parser`` in new
code so persistence queries and document validation stay separate.
"""

from .capability.catalog import enabled_skills, enabled_tool_names, skill_catalog
from .capability.skill_parser import MAX_SKILL_BYTES, SKILL_NAME_RE, parse_skill_document

__all__ = [
    "MAX_SKILL_BYTES", "SKILL_NAME_RE", "enabled_skills", "enabled_tool_names",
    "parse_skill_document", "skill_catalog",
]
