"""Code-owned registry. User/model/document content can never register tools."""

from __future__ import annotations

from typing import Iterable

from .base import AgentTool, ToolError


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, AgentTool] = {}

    def register(self, tool: AgentTool) -> None:
        name = tool.definition.name
        if name in self._tools:
            raise ValueError(f"tool already registered: {name}")
        self._tools[name] = tool

    def replace(self, tool: AgentTool) -> None:
        self._tools[tool.definition.name] = tool

    def get(self, name: str) -> AgentTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolError("TOOL_NOT_REGISTERED", "请求的工具未注册") from exc

    def available(self, permissions: Iterable[str] = ()) -> list[AgentTool]:
        allowed = frozenset(permissions)
        return [
            tool
            for tool in self._tools.values()
            if set(tool.definition.required_permissions).issubset(allowed)
        ]

    def definitions(self, permissions: Iterable[str] = ()) -> list[dict]:
        return [tool.definition.model_dump(mode="json") for tool in self.available(permissions)]

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))


_registry = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    return _registry
