"""Unified runtime capability boundary for Tool, Skill and MCP adapters.

The Agent depends on this small interface instead of knowing how a capability
is implemented or where it came from. Enablement is applied before a resolver
is created, so disabled capabilities are not visible to routing or execution.
"""

from __future__ import annotations

from ..tools.executor import ToolExecutor
from ..tools.registry import ToolRegistry


class CapabilityResolver:
    def __init__(self, registry: ToolRegistry, *, executor: ToolExecutor | None = None):
        self.registry = registry
        self.executor = executor or ToolExecutor(registry)

    def names(self) -> tuple[str, ...]:
        return self.registry.names()

    def catalog(self, permissions=()):
        return self.registry.catalog(permissions)

    def definition(self, name: str, permissions=()):
        return self.registry.definition(name, permissions)

    def execute(self, proposal, context, *, confirmed=False):
        return self.executor.execute(proposal, context, confirmed=confirmed)
