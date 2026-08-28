"""Progressively disclosed skill loader.

Only name and description are exposed during planning. Full SKILL.md content
is loaded into the run context only after the model selects this tool.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from sqlalchemy import select

from ...db.models.capability import AgentSkill
from ..capabilities import SKILL_NAME_RE
from ..contracts.tool import ToolDefinition, ToolResultEnvelope
from .base import ToolContext, ToolError


class SkillLoadInput(BaseModel):
    name: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]{1,63}$")


class SkillLoadOutput(BaseModel):
    name: str
    version: str
    content: str


class SkillLoadTool:
    input_model = SkillLoadInput
    output_model = SkillLoadOutput
    definition = ToolDefinition(
        name="skill.load",
        version="1.0",
        description="按需加载一个已启用技能的详细 SKILL.md 指导；只在任务与技能描述匹配时调用。",
        input_schema=SkillLoadInput.model_json_schema(),
        output_schema=SkillLoadOutput.model_json_schema(),
        layer="RESOURCE",
        owner="platform",
        risk="READ_ONLY",
        side_effect=False,
        requires_confirmation=False,
        idempotency="NOT_APPLICABLE",
        required_permissions=["skill:read"],
        timeout_seconds=10,
        max_retries=0,
        max_result_bytes=9_500_000,
        sensitivity="INTERNAL",
    )

    def execute(self, args: SkillLoadInput, context: ToolContext) -> ToolResultEnvelope:
        if context.session_factory is None or not SKILL_NAME_RE.fullmatch(args.name):
            raise ToolError("TOOL_CONTEXT_INVALID", "技能名称无效")
        with context.session_factory() as db:
            skill = db.execute(
                select(AgentSkill).where(AgentSkill.name == args.name, AgentSkill.enabled.is_(True))
            ).scalar_one_or_none()
            if skill is None:
                raise ToolError("SKILL_NOT_FOUND", "技能不存在或未启用")
            output = SkillLoadOutput(name=skill.name, version=skill.version, content=skill.content)
        now = datetime.now(timezone.utc)
        return ToolResultEnvelope(
            call_id=str(context.metadata.get("call_id") or uuid.uuid4()),
            tool_name=self.definition.name,
            tool_version=self.definition.version,
            status="SUCCEEDED",
            data=output.model_dump(mode="json"),
            summary=f"已按需加载技能 {args.name}",
            sensitivity=self.definition.sensitivity,
            started_at=now,
            completed_at=datetime.now(timezone.utc),
        )


def register_skill_tools(registry) -> None:
    registry.register(SkillLoadTool())
