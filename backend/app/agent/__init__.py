"""LangGraph 知识助手 Agent（DD-21）。

- state.py：AgentState（可 JSON 序列化）与 DTO；
- context.py：AgentRuntimeContext（运行依赖，不进入 checkpoint）；
- memory.py：会话记忆、token 预算与滚动摘要；
- policies.py：路由、证据、预算与循环上限策略；
- errors.py：类型化 Agent 错误；
- graph.py：StateGraph 构建与条件边；
- runtime.py：invoke/resume、checkpointer 与截止时间。
- nodes/：职责单一、可独立单测的节点。
"""

from __future__ import annotations

__version__ = "1.0"
