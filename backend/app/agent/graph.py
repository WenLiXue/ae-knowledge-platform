"""LangGraph 主图（DD-21 §7）。

节点注册、条件边和图编译。所有节点出边都是条件边：先检查 _terminate → persist_result，
保证取消/超时/步数上限在任何节点进入时都能收敛到持久化。
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .context import AgentRuntimeContext
from .nodes import (
    agent_loop as agent_loop_node,
    build_context as build_context_node,
    load_state as load_state_node,
    persist_result as persist_node,
    update_memory as update_memory_node,
)
from .nodes import node as wrap
from .policies import route_after_load
from .state import AgentState


def _route_fixed(next_node: str):
    def router(state: AgentState) -> str:
        if state.get("_terminate"):
            return "persist_result"
        return next_node

    return router


def build_agent_graph(*, checkpointer=None, context_schema=AgentRuntimeContext):
    builder = StateGraph(AgentState, context_schema=context_schema)

    builder.add_node("load_state", wrap("load_state")(load_state_node.core_load_state))
    builder.add_node("build_context", wrap("build_context")(build_context_node.core_build_context))
    builder.add_node("agent_loop", wrap("agent_loop")(agent_loop_node.core_agent_loop))
    builder.add_node("update_memory", wrap("update_memory")(update_memory_node.core_update_memory))
    builder.add_node("persist_result", wrap("persist_result", check_limits=False)(persist_node.core_persist_result))

    builder.add_edge(START, "load_state")
    builder.add_conditional_edges("load_state", route_after_load, ["build_context", "persist_result"])
    builder.add_edge("build_context", "agent_loop")
    builder.add_conditional_edges("agent_loop", _route_fixed("update_memory"), ["update_memory", "persist_result"])
    builder.add_conditional_edges("update_memory", _route_fixed("persist_result"), ["persist_result"])
    builder.add_edge("persist_result", END)

    return builder.compile(checkpointer=checkpointer)
