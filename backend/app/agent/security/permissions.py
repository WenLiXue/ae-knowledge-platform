"""Central permission composition for Agent planning and execution.

Keeping this in one place prevents planner and runtime from drifting apart.
The returned set is intentionally scoped to a single run.
"""

from __future__ import annotations

from collections.abc import Iterable


READ_PERMISSIONS = frozenset({
    "knowledge:read",
    "skill:read",
    "mcp:read",
    "filesystem:read",
})


def permissions_for_run(*, write_tools_enabled: bool, extra: Iterable[str] = ()) -> frozenset[str]:
    permissions = set(READ_PERMISSIONS)
    if write_tools_enabled:
        permissions.add("task:write")
    permissions.update(extra)
    return frozenset(permissions)
