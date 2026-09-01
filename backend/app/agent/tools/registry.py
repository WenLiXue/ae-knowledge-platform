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

    def remove(self, name: str) -> None:
        """Remove a capability from the runtime-visible registry."""
        self._tools.pop(name, None)

    def get(self, name: str) -> AgentTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolError("TOOL_NOT_REGISTERED", "请求的工具未注册") from exc

    def available(
        self,
        permissions: Iterable[str] = (),
        *,
        layers: Iterable[str] | None = None,
    ) -> list[AgentTool]:
        allowed = frozenset(permissions)
        allowed_layers = frozenset(layers) if layers is not None else None
        return [
            tool
            for tool in self._tools.values()
            if set(tool.definition.required_permissions).issubset(allowed)
            and (allowed_layers is None or tool.definition.layer in allowed_layers)
        ]

    def definitions(
        self,
        permissions: Iterable[str] = (),
        *,
        layers: Iterable[str] | None = None,
    ) -> list[dict]:
        return [
            tool.definition.model_dump(mode="json")
            for tool in self.available(permissions, layers=layers)
        ]

    def catalog(
        self,
        permissions: Iterable[str] = (),
        *,
        layers: Iterable[str] | None = None,
    ) -> list[dict]:
        """Return the lightweight first-stage catalog for progressive disclosure.

        The planner/router sees only routing metadata initially; input/output
        schemas are loaded later with :meth:`definition` after a tool is chosen.
        """
        return [
            {
                "name": tool.definition.name,
                "version": tool.definition.version,
                "description": tool.definition.description,
                "layer": tool.definition.layer,
                "risk": tool.definition.risk,
                "side_effect": tool.definition.side_effect,
            }
            for tool in self.available(permissions, layers=layers)
        ]

    def definition(self, name: str, permissions: Iterable[str] = ()) -> dict:
        """Load one tool's full schema after routing selects it."""
        tool = self.get(name)
        allowed = frozenset(permissions)
        if not set(tool.definition.required_permissions).issubset(allowed):
            raise ToolError("TOOL_PERMISSION_DENIED", "当前用户没有权限使用该工具")
        return tool.definition.model_dump(mode="json")

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))


_registry = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    return _registry
