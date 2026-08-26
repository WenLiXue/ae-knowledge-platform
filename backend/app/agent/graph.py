"""LangGraph 主图（DD-21 §7）。

节点注册、条件边和图编译。所有节点出边都是条件边：先检查 _terminate → persist_result，
保证取消/超时/步数上限在任何节点进入时都能收敛到持久化。
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .context import AgentRuntimeContext
from .nodes import (
    assess_evidence as assess_node,
    build_context as build_context_node,
    generate as generate_node,
    load_state as load_state_node,
    persist_result as persist_node,
    retrieve as retrieve_node,
    rewrite_query as rewrite_node,
    route_intent as route_intent_node,
    update_memory as update_memory_node,
    validate as validate_node,
)
from .nodes import node as wrap
from .policies import (
    route_after_evidence,
    route_after_intent,
    route_after_load,
    route_after_validation,
)
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
    builder.add_node("route_intent", wrap("route_intent")(route_intent_node.core_route_intent))
    builder.add_node("generate_general", wrap("generate_general")(generate_node.core_generate_general))
    builder.add_node("generate_grounded", wrap("generate_grounded")(generate_node.core_generate_grounded))
    builder.add_node("finalize_clarification", wrap("finalize_clarification")(generate_node.core_finalize_clarification))
    builder.add_node("finalize_insufficient", wrap("finalize_insufficient")(generate_node.core_finalize_insufficient))
    builder.add_node("retrieve", wrap("retrieve")(retrieve_node.core_retrieve))
    builder.add_node("assess_evidence", wrap("assess_evidence")(assess_node.core_assess_evidence))
    builder.add_node("rewrite_query", wrap("rewrite_query")(rewrite_node.core_rewrite_query))
    builder.add_node("validate_citations", wrap("validate_citations")(validate_node.core_validate_citations))
    builder.add_node("update_memory", wrap("update_memory")(update_memory_node.core_update_memory))
    builder.add_node("persist_result", wrap("persist_result", check_limits=False)(persist_node.core_persist_result))

    builder.add_edge(START, "load_state")
    builder.add_conditional_edges("load_state", route_after_load, ["build_context", "persist_result"])
    builder.add_conditional_edges(
        "build_context", _route_fixed("route_intent"), ["route_intent", "persist_result"]
    )
    builder.add_conditional_edges(
        "route_intent",
        lambda state: route_after_intent(state),
        ["retrieve", "generate_general", "finalize_clarification", "persist_result"],
    )
    builder.add_conditional_edges(
        "retrieve", _route_fixed("assess_evidence"), ["assess_evidence", "persist_result"]
    )
    builder.add_conditional_edges(
        "assess_evidence",
        lambda state: route_after_evidence(state),
        ["rewrite_query", "generate_grounded", "finalize_insufficient", "persist_result"],
    )
    builder.add_conditional_edges("rewrite_query", _route_fixed("retrieve"), ["retrieve", "persist_result"])
    builder.add_conditional_edges(
        "generate_general", _route_fixed("update_memory"), ["update_memory", "persist_result"]
    )
    builder.add_conditional_edges(
        "finalize_clarification", _route_fixed("update_memory"), ["update_memory", "persist_result"]
    )
    builder.add_conditional_edges(
        "finalize_insufficient", _route_fixed("update_memory"), ["update_memory", "persist_result"]
    )
    builder.add_conditional_edges(
        "generate_grounded", _route_fixed("validate_citations"), ["validate_citations", "persist_result"]
    )
    builder.add_conditional_edges(
        "validate_citations",
        lambda state: route_after_validation(state),
        ["update_memory", "generate_grounded", "finalize_insufficient", "persist_result"],
    )
    builder.add_conditional_edges("update_memory", _route_fixed("persist_result"), ["persist_result"])
    builder.add_edge("persist_result", END)

    return builder.compile(checkpointer=checkpointer)
