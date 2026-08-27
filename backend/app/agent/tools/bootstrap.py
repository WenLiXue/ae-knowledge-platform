"""Application-owned tool registry construction."""

from __future__ import annotations

from .knowledge import register_knowledge_tools
from .registry import ToolRegistry


def build_default_tool_registry() -> ToolRegistry:
    """Build a fresh registry for an application/worker process.

    A fresh registry avoids test and process-global registration leakage. Only
    code-owned adapters are registered here; model output cannot mutate it.
    """
    registry = ToolRegistry()
    register_knowledge_tools(registry)
    return registry
