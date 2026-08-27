"""Non-bypassable policy checks before a tool can execute."""

from __future__ import annotations

from .base import ToolContext, ToolError
from ..contracts.tool import ToolDefinition


class ToolPolicy:
    def __init__(self, *, allow_write: bool = False, allow_high_risk: bool = False) -> None:
        self.allow_write = allow_write
        self.allow_high_risk = allow_high_risk

    def authorize(self, definition: ToolDefinition, context: ToolContext, *, confirmed: bool = False) -> None:
        required = set(definition.required_permissions)
        if not required.issubset(context.permissions):
            raise ToolError("TOOL_PERMISSION_DENIED", "当前用户没有调用该工具的权限")
        if definition.risk == "HIGH_RISK" and not self.allow_high_risk:
            raise ToolError("TOOL_HIGH_RISK_DISABLED", "高风险工具当前未启用")
        if definition.side_effect and not self.allow_write:
            raise ToolError("WRITE_TOOLS_DISABLED", "写工具当前未启用")
        if definition.requires_confirmation and not confirmed:
            raise ToolError("APPROVAL_REQUIRED", "该工具执行前需要用户确认")
