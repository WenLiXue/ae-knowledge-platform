# AE 内部知识平台 LangGraph 知识助手 Agent 重构详细设计

版本：V0.1  
状态：可实施讨论稿  
日期：2026-08-26  
编号：DD-21  
目标读者：实现 Agent、后端开发、测试、运维和技术评审人员

## 1. 文档目的

本文定义如何使用 LangGraph 重构当前知识助手的会话编排。它不是概念说明，而是可直接交给编码 Agent 执行的实现契约。

重构后的助手必须先理解用户意图，再决定是否调用知识库；不得把所有问题都强制转为 RAG 查询。它同时必须具备有界的会话记忆、可恢复的执行状态、清晰的迭代上限，以及与现有 Worker、模型网关、检索服务、答案和引用表兼容的持久化行为。

本文回答以下问题：

- 为什么选择 LangGraph，而不是继续扩展手写流程或使用黑盒 AgentExecutor；
- Agent 有哪些状态、节点、条件边和失败路径；
- 普通对话、知识问答、解释、澄清、总结和关联查询分别如何路由；
- 会话记忆保存什么、保留多长、何时压缩，以及什么不能作为事实依据；
- LangGraph 循环、模型重试、检索改写和 Worker 重试分别限制多少次；
- 如何复用当前代码并分阶段迁移，出现问题时如何回滚；
- 实现完成后由哪些自动化测试和验收场景证明正确。

## 2. 上游基线与当前实现证据

### 2.1 上游设计约束

本设计继承以下文档，不重新定义其业务事实：

- DD-07《RAG 检索与问答》：混合检索、证据、引用和降级边界；
- DD-10《会话、导出与分享》：会话、消息、答案和引用生命周期；
- DD-15《Agent 编排与业务能力》：知识助手业务能力及“内部产品事实必须来自证据”的原则；
- DD-19《分类与 RAG 完整实施设计》：分类、文档元数据和检索链路；
- DD-20《LLM 模型管理与服务配置》：模型连接、业务绑定和服务商协议。

若本文与上述文档冲突，优先遵循以下不变量：

1. PostgreSQL 是业务状态唯一事实来源；
2. 搜索索引和 LangGraph checkpoint 都是可重建或可清理的派生运行数据；
3. 内部产品事实必须由本轮证据支持；
4. 引用只能指向本轮检索得到的有效文档版本和切片；
5. 一个会话同一时刻最多只有一个未完成答案；
6. 任务可以重试，但最终业务写入必须幂等。

### 2.2 当前代码事实

截至本文日期，仓库已有以下实现：

| 能力 | 当前落点 | 结论 |
|---|---|---|
| 创建问题和答案任务 | `backend/app/conversation/service.py` | 同一事务创建用户消息、`PENDING` 答案和 `GENERATE_ANSWER` 任务 |
| 任务领取、租约和重试 | `backend/app/worker/runner.py` | 已有 Worker 级重试，最终失败会同步答案状态 |
| 任务阶段分发 | `backend/app/worker/pipeline.py` | `GENERATE_ANSWER` 进入现有问答 Worker |
| 手写问答编排 | `backend/app/qa/worker.py` | 当前按函数顺序完成上下文、意图、检索、生成、校验和持久化 |
| 查询理解与生成 | `backend/app/qa/llm.py`、`schemas.py` | 已有结构化意图和生成结果协议 |
| RAG | `backend/app/retrieval/service.py` | 已有独立 `RetrievalService`，不应在 LangGraph 内重写 |
| 模型调用 | `backend/app/model_gateway/` | 已支持不同服务商协议和业务模型绑定，应继续作为唯一模型出口 |
| 会话历史 | 会话、消息、答案和引用数据库表 | 已保存完整历史，但当前只读取固定最近 6 条并截断摘要 |

当前不足：

- 编排逻辑集中在单个 Worker 函数中，分支和恢复点不清晰；
- 没有独立的 Agent 运行记录和节点级观测；
- “记忆”只是固定数量的最近消息，不按模型上下文窗口或 token 预算管理；
- 没有滚动摘要、实体、用户约束和待解决问题等结构化会话记忆；
- 没有真正的图执行恢复；进程中断后只能从整个 Worker 任务重新开始；
- 重试、修复和图循环的概念混在一起，无法解释“最多迭代多少次”；
- 后续继续扩展工具或路由时，容易形成更大的条件分支函数。

## 3. 技术决策

### 3.1 选择 LangGraph

采用 LangGraph `StateGraph` 作为知识助手编排引擎。

选择理由：

- 路由和循环可以显式表示为节点与条件边，便于测试和评审；
- 支持 checkpoint，可从已完成节点恢复，适合当前异步 Worker 模式；
- 状态是类型化数据，便于约束节点输入输出和做持久化；
- 可以为每种修复循环设置独立上限，不需要开放式自主工具循环；
- 可继续使用当前模型网关和检索服务，不要求迁移到 LangChain 的模型或向量库实现。

不采用以下方案：

- 不使用 LangChain `AgentExecutor` 作为主编排器；其隐式循环和工具选择不符合本项目的可审计要求；
- 不让 LLM 自由决定任意工具名称和参数；V1 使用受控意图路由和白名单能力；
- 不用 LangGraph checkpoint 代替业务数据库；checkpoint 只服务于执行恢复；
- 不在本次重构中替换 OpenSearch、Embedding、Rerank 或现有模型配置系统。

### 3.2 依赖基线

当前项目运行于 Python 3.11 以上，环境实测为 Python 3.12。实现 Agent 应在 `backend/pyproject.toml` 中加入有界版本依赖：

```toml
langgraph = ">=1.2,<1.3"
langgraph-checkpoint-postgres = ">=3.1,<3.2"
langchain-core = ">=1.6,<1.7" # 仅在 LangGraph 类型或消息抽象确有需要时加入
```

版本来源为 2026-08-26 的包索引结果：`langgraph 1.2.11`、`langgraph-checkpoint-postgres 3.1.2`、`langchain-core 1.6.0`。实现时必须用项目锁文件重新解析依赖，并以锁文件和自动化测试为最终基线；不得在业务代码里依赖未固定的小版本私有 API。

### 3.3 架构决定清单

| 编号 | 决定 | 状态 |
|---|---|---|
| ADR-LG-001 | 使用 LangGraph `StateGraph`，不使用开放式 AgentExecutor | 推荐基线 |
| ADR-LG-002 | PostgreSQL 业务表为事实源，checkpoint 为运行恢复数据 | 推荐基线 |
| ADR-LG-003 | `thread_id` 使用 `answer_id`，而非 `conversation_id` | 推荐基线 |
| ADR-LG-004 | 会话记忆单独保存，不从 checkpoint 读取业务记忆 | 推荐基线 |
| ADR-LG-005 | 复用 `RetrievalService` 和 `model_gateway` | 已确认 |
| ADR-LG-006 | V1 不提供无上限自主工具循环 | 推荐基线 |
| ADR-LG-007 | 使用 feature flag 分阶段迁移并保留旧路径回滚 | 推荐基线 |

## 4. 目标架构

```text
HTTP API
  │ 创建 Message + Answer + ProcessingTask
  ▼
Worker runner / lease / retry
  ▼
qa.worker（薄适配器）
  ▼
LangGraph Knowledge Assistant
  ├─ Context Builder ───── PostgreSQL 会话消息/滚动记忆
  ├─ Intent Router ─────── model_gateway（结构化输出）
  ├─ Retrieval Tool ────── RetrievalService → OpenSearch/Embedding/Rerank
  ├─ Answer Generator ──── model_gateway
  ├─ Citation Validator ── 本地确定性校验
  ├─ Memory Manager ────── PostgreSQL conversation_memories
  └─ Result Persister ──── Answer + AnswerCitation + AgentRun

LangGraph PostgresSaver
  └─ agent_runtime schema（仅 checkpoint，不是业务事实源）
```

### 4.1 组件职责

| 组件 | 负责 | 不负责 |
|---|---|---|
| LangGraph | 编排、条件路由、有界循环、checkpoint 恢复 | 模型服务商协议、向量检索实现、业务事实持久化 |
| Model Gateway | 选择实际模型、协议适配、超时和传输重试 | 决定业务路由、保存会话记忆 |
| RetrievalService | 查询计划、BM25/向量召回、融合、Rerank、证据 | 对话记忆、最终答案编排 |
| Memory Manager | 上下文预算、滚动摘要、实体和约束 | 充当知识库或长期个人画像 |
| Worker | 任务租约、进程级重试、取消和最终失败同步 | 图内部节点选择 |
| Result Persister | 原子写入答案、引用和运行结果 | 远程模型调用 |

### 4.2 建议代码目录

```text
backend/app/agent/
  __init__.py
  state.py                 # AgentState、序列化 DTO
  context.py               # AgentRuntimeContext，只保存运行依赖
  graph.py                 # StateGraph 构建和条件边
  runtime.py               # invoke/resume、checkpointer、deadline
  policies.py              # 路由、预算、循环上限和证据策略
  errors.py                # 类型化错误
  memory.py                # MemoryManager 和 token 预算
  nodes/
    load_state.py
    build_context.py
    route_intent.py
    retrieve.py
    assess_evidence.py
    generate.py
    validate.py
    update_memory.py
    persist_result.py
```

保留 `backend/app/qa/` 中提示词、结构化 Schema 和答案校验能力。迁移完成后，`backend/app/qa/worker.py` 只负责把 Worker 任务转换为 `AgentState` 并调用运行时；不得继续保存第二套分支编排。

## 5. Agent 状态设计

### 5.1 状态原则

1. `AgentState` 必须可 JSON 序列化；
2. 不得放入 SQLAlchemy Session、模型客户端、检索服务实例或数据库实体对象；
3. 大型证据正文应限制长度，必要时只保存证据 DTO；
4. 密钥、Authorization、完整模型请求头不得进入状态或 checkpoint；
5. 节点返回状态增量，不原地修改共享对象；
6. 所有计数器和降级标志必须显式保存，恢复后不能重新从零计数。

### 5.2 `AgentState`

建议使用 `TypedDict`，边界输入输出使用 Pydantic 校验：

```python
class AgentState(TypedDict, total=False):
    # 身份与幂等
    run_id: str
    answer_id: str
    conversation_id: str
    user_id: str
    graph_version: str

    # 输入
    question: str
    filters_snapshot: dict[str, object]
    cancel_requested: bool

    # 会话上下文
    recent_turns: list[dict[str, str]]
    memory_summary: str
    memory_entities: list[dict[str, str]]
    memory_constraints: list[str]
    unresolved_topics: list[str]
    context_token_estimate: int

    # 查询理解与路由
    operation: str
    normalized_question: str
    requires_retrieval: bool
    clarification_question: str | None
    query_entities: list[str]
    route_reason_code: str

    # 检索
    retrieval_run_id: str | None
    retrieval_queries: list[str]
    evidence: list[dict[str, object]]
    evidence_quality: str
    degradation_flags: list[str]

    # 生成与校验
    answer_text: str
    answer_summary: str
    answer_confidence: str
    citation_drafts: list[dict[str, object]]
    validation_errors: list[str]

    # 有界循环
    step_count: int
    intent_repair_count: int
    query_rewrite_count: int
    citation_repair_count: int

    # 记忆更新与终态
    memory_patch: dict[str, object]
    final_status: str
    error_code: str | None
    error_summary: str | None
    node_trace: list[dict[str, object]]
```

不得直接使用 `add_messages` 累积全量消息。项目已经有自己的消息、答案和引用领域模型；LangChain 消息列表会重复保存内容，并让 checkpoint 持续膨胀。`recent_turns` 只包含本轮上下文预算选中的有限历史。

### 5.3 运行依赖 `AgentRuntimeContext`

运行依赖通过 LangGraph `context_schema` 或图工厂闭包注入，不进入 checkpoint：

```python
@dataclass(frozen=True)
class AgentRuntimeContext:
    session_factory: sessionmaker
    retrieval_service_factory: Callable[[], RetrievalService]
    model_gateway_resolver: ModelGatewayResolver
    settings: Settings
    tokenizer: TokenEstimator
    clock: Clock
```

每个节点自己创建短生命周期数据库 Session。禁止跨模型 HTTP 调用持有数据库事务或行锁。

## 6. 意图与路由契约

### 6.1 支持的操作

沿用现有结构化操作枚举：

| operation | 含义 | 默认检索 |
|---|---|---|
| `CHAT` | 问候、闲聊、能力说明、非内部知识的一般对话 | 否 |
| `CLARIFY` | 输入不足，需要用户补充产品、版本、对象或问题 | 否 |
| `ANSWER` | 回答内部产品、功能、配置、行为或问题 | 是 |
| `SUMMARIZE` | 总结指定内部文档、产品或本轮证据 | 是 |
| `RELATE` | 比较、关联多个内部对象或文档 | 是 |
| `EXPLAIN` | 解释概念；可为一般解释，也可为内部产品解释 | 条件判断 |

`EXPLAIN` 满足任一条件时检索：

- 问题包含已识别产品、版本、模块或内部术语；
- 会话过滤器已限定产品、版本或文档类型；
- 用户使用“这个产品”“上一版”“刚才那份文档”等指代，且记忆可解析为内部对象；
- 用户明确要求“根据知识库/文档/公司资料”。

天气、时事、互联网搜索等不属于当前工具范围。Agent 必须明确说明能力边界，不能将它们伪装成知识库答案。

### 6.2 路由输出 Schema

查询理解模型必须输出受控 Schema：

```json
{
  "operation": "ANSWER",
  "normalized_question": "AE 信被防毒墙如何配置 REST 接口访问控制？",
  "requires_retrieval": true,
  "clarification_question": null,
  "entities": ["AE信被防毒墙", "REST接口"],
  "resolved_references": [],
  "reason_code": "INTERNAL_PRODUCT_QUESTION"
}
```

规则：

- `requires_retrieval` 由 Schema 校验后再经过本地策略二次约束，不能完全信任模型；
- `ANSWER/SUMMARIZE/RELATE` 不得被模型错误改为无检索直接回答内部事实；
- Schema 解析失败最多修复 1 次；再次失败时采用保守路由：内部实体或产品过滤器存在则检索，否则进入澄清；
- 路由模型不能生成最终答案。

## 7. LangGraph 图设计

### 7.1 主图

```text
START
  │
  ▼
load_state ──取消/终态──► END
  │
  ▼
build_context
  │
  ▼
route_intent
  ├─ CLARIFY ─────────────► finalize_clarification
  ├─ CHAT ────────────────► generate_general
  ├─ EXPLAIN(无需检索) ───► generate_general
  └─ 需要知识库 ──────────► retrieve
                                │
                                ▼
                         assess_evidence
                          ├─ 无证据 ─────► finalize_insufficient
                          ├─ 需改写且未达上限 ─► rewrite_query ─► retrieve
                          └─ 有效/部分/冲突 ──► generate_grounded
                                                   │
                                                   ▼
                                            validate_citations
                                             ├─ 可修复且未达上限 ─► generate_grounded
                                             ├─ 不可修复 ─────────► finalize_insufficient
                                             └─ 通过

所有正常分支
  ▼
update_memory
  ▼
persist_result
  ▼
END
```

所有未捕获异常必须转换为类型化 Agent 错误，由运行时映射到现有答案失败语义；不得在任意节点吞掉异常并生成看似成功的回答。

### 7.2 节点契约

| 节点 | 读取 | 输出 | 外部副作用 |
|---|---|---|---|
| `load_state` | answer_id | 问题、会话、用户、过滤器、取消状态 | 短事务更新 AgentRun 为 RUNNING |
| `build_context` | conversation_id、message_id | recent_turns、memory_*、预算 | 只读数据库 |
| `route_intent` | question、context、filters | operation、normalized、route | 调用意图模型 |
| `finalize_clarification` | understanding | 澄清问题和低置信提示 | 无 |
| `generate_general` | question、recent_turns、summary | 一般对话回答 | 调用生成模型；不得注入知识证据 |
| `retrieve` | normalized、filters | RetrievalResult DTO | 调用现有 RetrievalService |
| `assess_evidence` | evidence、降级信息 | quality、下一路径 | 本地规则为主；可选小模型不得改变证据集合 |
| `rewrite_query` | question、理解、召回摘要 | 新查询 | 调用模型，最多一次 |
| `generate_grounded` | evidence、context | 答案、引用草稿 | 调用生成模型 |
| `validate_citations` | answer、citations、evidence | 校验错误或通过 | 本地确定性校验 |
| `finalize_insufficient` | evidence quality | 明确的不足/冲突回答 | 无 |
| `update_memory` | 本轮问答和旧记忆 | memory_patch | 可调用摘要模型；不得写产品事实为长期真相 |
| `persist_result` | 终态内容 | final_status | 原子写 Answer、Citation、Memory、AgentRun |

### 7.3 节点实现规则

- 一个节点只完成一种业务职责；
- 节点必须可以用输入状态和替身依赖独立单测；
- 除 `load_state`、进度记录和 `persist_result` 外，节点不得写业务表；
- `retrieve` 必须直接调用 `RetrievalService.retrieve()`，不得复制检索参数或另写 OpenSearch 查询；
- `generate_grounded` 必须继续调用模型网关，不直接实例化 OpenAI/Anthropic SDK；
- `validate_citations` 校验引用 ID 属于本轮 evidence、引用目标仍有效、答案中的标号可解析；
- `update_memory` 失败不应让已生成且已验证的答案失败，应增加 `MEMORY_UPDATE_FAILED` 降级标志并继续持久化；
- 每个节点进入和退出时检查取消与总截止时间。

### 7.4 图构建骨架

以下代码用于说明结构，不得直接复制后跳过当前版本 API 验证：

```python
from langgraph.graph import END, START, StateGraph

def build_knowledge_graph(*, checkpointer):
    builder = StateGraph(AgentState, context_schema=AgentRuntimeContext)

    builder.add_node("load_state", load_state)
    builder.add_node("build_context", build_context)
    builder.add_node("route_intent", route_intent)
    builder.add_node("generate_general", generate_general)
    builder.add_node("retrieve", retrieve)
    builder.add_node("assess_evidence", assess_evidence)
    builder.add_node("rewrite_query", rewrite_query)
    builder.add_node("generate_grounded", generate_grounded)
    builder.add_node("validate_citations", validate_citations)
    builder.add_node("finalize_clarification", finalize_clarification)
    builder.add_node("finalize_insufficient", finalize_insufficient)
    builder.add_node("update_memory", update_memory)
    builder.add_node("persist_result", persist_result)

    builder.add_edge(START, "load_state")
    builder.add_conditional_edges("load_state", route_after_load)
    builder.add_edge("build_context", "route_intent")
    builder.add_conditional_edges("route_intent", route_after_intent)
    builder.add_edge("retrieve", "assess_evidence")
    builder.add_conditional_edges("assess_evidence", route_after_evidence)
    builder.add_edge("rewrite_query", "retrieve")
    builder.add_edge("generate_grounded", "validate_citations")
    builder.add_conditional_edges("validate_citations", route_after_validation)

    for terminal_answer_node in (
        "generate_general",
        "finalize_clarification",
        "finalize_insufficient",
    ):
        builder.add_edge(terminal_answer_node, "update_memory")

    builder.add_edge("update_memory", "persist_result")
    builder.add_edge("persist_result", END)
    return builder.compile(checkpointer=checkpointer)
```

运行配置：

```python
config = {
    "configurable": {"thread_id": str(answer_id)},
    "recursion_limit": settings.agent_max_steps,
}
graph.invoke(initial_state, config=config, context=runtime_context)
```

实现 Agent 必须针对锁定的 LangGraph 1.2.x API 编写一个最小编译和 invoke 测试，确认 `context_schema`、Postgres checkpointer 和 `recursion_limit` 的实际调用方式。

## 8. 记忆系统

### 8.1 三层记忆模型

| 层级 | 内容 | 保存位置 | 生命周期 | 是否可作为内部事实依据 |
|---|---|---|---|---|
| 完整历史 | 用户消息、答案、引用 | 现有业务表 | 会话生命周期 | 引用仍需本轮重新检索验证 |
| 工作记忆 | 本轮选中的 recent turns、证据、路由状态 | AgentState/checkpoint | 单个 answer run | 仅本轮 |
| 会话记忆 | 滚动摘要、实体、用户约束、待解决主题 | `conversation_memories` | 会话生命周期 | 否 |

V1 不实现跨会话的用户长期画像。若以后需要记住用户偏好，必须另行设计授权、可查看、可修改、可删除和数据保留策略，不能悄悄从历史会话提取个人信息。

### 8.2 会话记忆包含什么

允许保存：

- 用户当前目标，例如“排查 REST 接口访问控制问题”；
- 已明确的产品、版本、模块和文档范围；
- 用户显式约束，例如“只看 V7.0”“用中文简要回答”；
- 尚未解决的问题；
- 前文代词解析需要的最近实体；
- 对话摘要，但应区分“用户陈述”和“知识库证据结论”。

禁止保存为可信事实：

- 没有来源的产品参数、配置值或漏洞结论；
- 模型推测的用户身份、权限或敏感属性；
- API Key、Token、口令和完整请求头；
- 大段原始文档正文；
- 已下线来源的内容作为后续回答依据。

### 8.3 token 预算，而不是固定 6 条

上下文构建必须按 token 预算选择，不再硬编码“最近 6 条”。建议初始配置：

- `conversation_recent_token_budget = 6000`；
- `conversation_summary_token_budget = 1500`；
- `conversation_compaction_trigger_ratio = 0.70`；
- 为模型输出预留 `max_output_tokens`；
- 证据预算由生成模型上下文窗口动态计算。

建议分配公式：

```text
available = model_context_window
            - system_prompt_tokens
            - reserved_output_tokens
            - safety_margin_tokens

history_budget  = min(config.recent_budget, available * 20%)
summary_budget  = min(config.summary_budget, available * 10%)
evidence_budget = available - history_budget - summary_budget - question_tokens
```

实际百分比必须通过黄金问题集和长对话测试调整。TokenEstimator 必须按实际模型选择对应 tokenizer；无法精确计算时采用保守估算并增加安全余量。

### 8.4 上下文选择算法

1. 读取当前会话记忆及其 `last_message_id`；
2. 从当前问题向前倒序读取消息和成功答案摘要；
3. 优先保留最近一轮用户问题及其回答；
4. 在 `recent_token_budget` 内继续加入更早完整轮次，不允许截成只有答案没有问题；
5. 加入滚动摘要、实体、约束和待解决主题；
6. 若当前问题含“它/这个/上一版”等指代，保证相关实体所在最近轮次优先进入；
7. 生成后记录实际 token 使用，用于校准估算器。

### 8.5 记忆压缩与更新

触发条件满足任一即可压缩：

- 未摘要的新消息 token 超过 `recent_token_budget * trigger_ratio`；
- 新增消息数超过建议阈值 12；
- 当前上下文即将超过模型窗口；
- 用户明确切换主题，需要关闭旧的 unresolved topic。

更新流程：

1. 将旧摘要和待压缩的完整轮次发送给摘要模型；
2. 要求输出结构化 `summary/entities/constraints/unresolved_topics`；
3. 本地 Schema 校验；失败最多修复 1 次；
4. 使用 `revision` 乐观锁更新；冲突时重新读取并合并一次；
5. 成功后推进 `last_message_id`；原始消息永不因摘要而删除。

失败策略：保留旧记忆，记录降级标志，不影响本轮已验证答案。

## 9. 迭代、重试和长度限制

这些限制必须区分，不能用一个“最大迭代次数”混淆全部行为。

| 层级 | 建议默认值 | 含义 | 达到上限后的行为 |
|---|---:|---|---|
| 图总步数 `agent_max_steps` | 12 | 单次 answer run 最多执行节点数，映射 recursion limit | 失败为 `AGENT_STEP_LIMIT_EXCEEDED` |
| 查询理解 Schema 修复 | 1 | 初次失败后最多再修一次 | 使用保守本地路由或澄清 |
| 检索 query rewrite | 1 | 低召回时最多改写一次 | 输出依据不足，不继续循环 |
| 引用修复 | 1 | 引用不合法时最多重新生成一次 | 输出依据不足或失败 |
| 记忆 Schema 修复 | 1 | 记忆摘要结构修复 | 跳过记忆更新并降级 |
| 模型传输重试 | 3 | 超时/限流等由 model gateway 控制 | 节点失败，交给 Worker |
| Worker `max_attempts` | 3 | 进程、依赖或可重试任务故障 | Answer 最终 FAILED |
| 单轮总截止时间 | 90 秒 | 包含路由、检索、生成和校验 | 取消后标记超时 |
| 用户问题长度 | 沿用现有 4000 字符 | API 输入限制 | API 直接拒绝 |

重要规则：

- 不允许“直到模型满意”为止的开放循环；
- 图恢复后继续使用 checkpoint 中的计数器，不重置上限；
- Worker 重试不是新的 Agent 迭代，仍使用相同 `answer_id/thread_id` 恢复；
- 不应同时在节点、模型网关和 Worker 对同一不可重试错误重复三层重试；
- 鉴权失败、Schema 业务校验失败、取消和明确配置错误不可重试。

## 10. 证据和答案策略

### 10.1 证据质量

`assess_evidence` 输出以下枚举：

| 值 | 条件 | 回答行为 |
|---|---|---|
| `SUFFICIENT` | 证据覆盖核心问题且来源有效 | 正常有依据回答 |
| `PARTIAL` | 只覆盖部分问题 | 回答已知部分并明确缺口 |
| `CONFLICTING` | 有效来源相互冲突 | 并列展示差异和版本/时间，不自行裁决 |
| `INSUFFICIENT` | 无有效证据或低于阈值 | 不生成内部事实，给出可操作澄清建议 |
| `UNAVAILABLE` | 检索依赖不可用且无可接受降级 | 明确系统失败，允许重试 |

### 10.2 引用校验不变量

1. 每个引用 ID 必须存在于本轮 evidence；
2. 引用保存的 source/version/chunk 必须与 evidence 一致；
3. 答案不得引用只出现在会话记忆、旧回答或模型常识中的内部事实；
4. 点击原文地址由现有来源定位契约生成，不能让模型生成 URL；
5. 无证据回答不展示空的“来源引用”；
6. 前端来源引用默认折叠属于展示层规则，后端只返回结构化引用数据。

## 11. 持久化设计

### 11.1 新增 `conversation.conversation_memories`

| 字段 | 类型 | 约束/说明 |
|---|---|---|
| `conversation_id` | UUID | PK、FK conversations、级联删除或随会话软删除策略 |
| `summary` | TEXT | 默认空字符串 |
| `entities` | JSONB | 结构化实体，默认 `[]` |
| `constraints` | JSONB | 用户显式约束，默认 `[]` |
| `unresolved_topics` | JSONB | 默认 `[]` |
| `last_message_id` | UUID NULL | 已压缩到的消息水位 |
| `token_estimate` | INT | 非负 |
| `revision` | INT | 乐观锁，默认 1 |
| `created_at` | TIMESTAMPTZ | 必填 |
| `updated_at` | TIMESTAMPTZ | 必填 |

索引：主键即可；如后续做后台治理，可增加 `updated_at` 索引。V1 不对 JSONB 内容做业务搜索。

### 11.2 新增 `conversation.agent_runs`

| 字段 | 类型 | 约束/说明 |
|---|---|---|
| `id` | UUID | PK |
| `answer_id` | UUID | UNIQUE、FK answers |
| `conversation_id` | UUID | FK conversations、索引 |
| `status` | VARCHAR | PENDING/RUNNING/SUCCEEDED/FAILED/CANCELED |
| `graph_version` | VARCHAR | 例如 `knowledge-assistant-v1` |
| `operation` | VARCHAR NULL | 最终路由结果 |
| `current_node` | VARCHAR NULL | 仅观测，不用于业务恢复 |
| `step_count` | INT | 实际节点数 |
| `max_steps` | INT | 本次快照值 |
| `checkpoint_thread_id` | VARCHAR | 等于 answer_id |
| `degradation_flags` | JSONB | 去重数组 |
| `timings` | JSONB | 节点耗时汇总，不存正文 |
| `token_usage` | JSONB | 按业务角色汇总 |
| `error_code` | VARCHAR NULL | 类型化错误 |
| `error_summary` | TEXT NULL | 脱敏摘要 |
| `started_at/completed_at` | TIMESTAMPTZ | 运行时间 |
| `created_at/updated_at` | TIMESTAMPTZ | 审计字段 |

V1 不新增逐步全文 `agent_steps` 表，防止重复保存提示词和证据。若运维确需逐节点追踪，先使用结构化日志和 `agent_runs.timings`；后续再单独评审保留期与脱敏。

### 11.3 LangGraph checkpoint

- 使用 `PostgresSaver`；
- checkpoint 表放在独立 `agent_runtime` schema；
- 使用受限数据库账号，只允许访问该 schema；
- `thread_id = answer_id`，保证一次答案生成对应一条执行时间线；
- 不使用 `conversation_id`，避免同一会话多轮状态互相覆盖或恢复到错误轮次；
- checkpoint 建表由独立 Alembic/初始化步骤管理，并在部署文档中明确；
- checkpoint 保留期建议 7～30 天，成功运行可异步清理；失败运行保留较长时间便于排查；
- 清理 checkpoint 不得删除答案、引用、消息和会话记忆。

### 11.4 事务和幂等

`persist_result` 使用短事务完成：

1. `SELECT answer FOR UPDATE`；
2. 若已为终态，验证与当前 run 是否一致后幂等返回；
3. 再次检查取消；
4. 写 Answer 内容、摘要、置信度、模型信息、检索 run 和降级标志；
5. 删除/替换该 answer 尚未发布的引用，或使用唯一键 upsert；
6. 写入全部 AnswerCitation；
7. 更新 AgentRun 终态；
8. 以 `revision` 更新 ConversationMemory，冲突时采用“答案成功、记忆降级”的策略；
9. 一次提交。

外部模型和检索调用绝不能放在该事务内。

## 12. Worker 与恢复语义

### 12.1 Worker 适配

`run_generate_answer()` 重构为薄入口：

```text
读取 task/answer 标识
  → 创建或读取 AgentRun
  → 构造初始 AgentState（只含 ID）
  → 使用 answer_id 作为 thread_id 调用图
  → 将类型化结果映射到现有 Worker 成功/失败协议
```

Worker 继续负责：

- ProcessingTask 领取、租约、心跳和 `max_attempts`；
- 进程崩溃后的任务回收；
- 不可恢复失败后将 Answer 置为 FAILED；
- 用户取消任务的入口。

LangGraph 负责：

- 从 checkpoint 恢复到最后成功节点；
- 保留本轮计数器、路由和已完成的检索结果；
- 避免成功节点在同一次恢复中被无意义重复执行。

### 12.2 典型恢复场景

| 故障点 | 恢复行为 |
|---|---|
| 路由模型超时 | 节点失败，Worker 重试；从最近 checkpoint 继续 |
| 检索完成后进程崩溃 | 恢复后复用 checkpoint 中序列化证据，不重复检索 |
| 生成完成、持久化前崩溃 | 从生成后 checkpoint 进入校验/持久化 |
| 持久化已提交、Worker 未确认 | 幂等读取终态并返回成功 |
| checkpoint 数据损坏或不可用 | 记录错误；允许 feature flag 回退旧路径或从业务输入重新开始一次 |
| 用户取消 | 节点边界检测后进入 CANCELED，不生成新答案 |

## 13. 配置设计

在 `backend/app/core/config.py` 中增加以下设置，并在 `.env.example`/部署文档同步：

| 配置 | 默认值 | 说明 |
|---|---:|---|
| `agent_graph_enabled` | `false` | 初始关闭，灰度后开启 |
| `agent_graph_version` | `knowledge-assistant-v1` | 写入 AgentRun |
| `agent_max_steps` | `12` | 图总步数硬限制 |
| `agent_timeout_seconds` | `90` | 单次总截止时间 |
| `agent_intent_repair_limit` | `1` | 意图 Schema 修复次数 |
| `agent_query_rewrite_limit` | `1` | 检索改写次数 |
| `agent_citation_repair_limit` | `1` | 引用修复次数 |
| `conversation_recent_token_budget` | `6000` | 最近完整轮次预算 |
| `conversation_summary_token_budget` | `1500` | 滚动摘要预算 |
| `conversation_compaction_trigger_ratio` | `0.70` | 压缩触发比例 |
| `agent_checkpoint_dsn` | 与业务库分离配置 | checkpoint 连接串，密钥不回传 API |
| `agent_checkpoint_retention_days` | `14` | 成功 checkpoint 保留期 |

默认值是实施起点，不是永久产品参数。性能、成本和长会话评测完成后再调整。

## 14. API、SSE 与前端兼容

### 14.1 对外 API

本次重构不改变现有创建会话、发送消息、读取消息、取消答案和 SSE 接口的 URL 与主要响应 Schema。

允许扩展但不能破坏兼容的字段：

- `answer.operation`：最终意图；
- `answer.degradation_flags`：包含图和记忆降级；
- `answer.progress_stage`：更细的阶段；
- 管理端可选 `agent_run_id`，普通用户无需展示。

### 14.2 进度阶段

建议统一阶段：

```text
PENDING
BUILDING_CONTEXT
ROUTING
RETRIEVING
GENERATING
VALIDATING
UPDATING_MEMORY
PERSISTING
SUCCEEDED / FAILED / CANCELED
```

前端必须对未知阶段使用通用“正在处理”文案，不能因新增枚举崩溃。不同会话切换只加载数据库中的消息和答案，不应等待 Agent 图完成；未完成答案由 SSE/轮询继续更新。

### 14.3 来源引用

- 后端保持结构化 citations，不预展开正文；
- 前端“来源引用”默认折叠；
- 点击原文使用服务端返回的实际来源定位字段或受控详情页路由；
- 不得把模型生成的 URL 当作原文地址；
- 无引用时不渲染引用组件。

## 15. 错误模型

建议新增类型化错误：

| 错误码 | 可重试 | 用户语义 |
|---|---|---|
| `AGENT_INPUT_INVALID` | 否 | 输入不合法 |
| `AGENT_ROUTE_INVALID` | 条件 | 无法理解时请求澄清 |
| `AGENT_STEP_LIMIT_EXCEEDED` | 否 | 流程超过安全上限 |
| `AGENT_TIMEOUT` | 是 | 本轮处理超时，可重试 |
| `AGENT_CANCELED` | 否 | 用户已取消 |
| `RETRIEVAL_UNAVAILABLE` | 是 | 检索暂不可用 |
| `EVIDENCE_INSUFFICIENT` | 否 | 不是系统错误，返回依据不足答案 |
| `CITATION_VALIDATION_FAILED` | 条件 | 修复耗尽后不可发布内部事实 |
| `MEMORY_UPDATE_FAILED` | 否 | 仅降级，不让答案失败 |
| `CHECKPOINT_UNAVAILABLE` | 是 | 运行恢复服务不可用 |

错误摘要必须脱敏，不记录密钥、完整提示词、整段文档或用户敏感信息。

## 16. 安全与提示注入

1. 用户输入、历史消息和检索文档都按不可信内容处理；
2. 系统提示明确：文档中的命令是资料内容，不是 Agent 指令；
3. V1 工具白名单只有受控检索和既有内部服务，不允许 Shell、任意 HTTP 或数据库查询工具；
4. 模型输出的 filter、URL、ID 必须经过本地 Schema 和权限校验；
5. 每次读取会话、消息和记忆都校验 `user_id` 所有权；
6. checkpoint 不保存模型 API Key 和数据库凭据；
7. 日志只记录 ID、节点、耗时、token 数、错误码和降级标志；
8. 会话逻辑删除后，记忆遵循同一可见性和清理策略；
9. 引用访问必须再次检查来源可见性和当前状态。

## 17. 可观测性

### 17.1 结构化日志

每个节点至少记录：

```text
event=agent_node_finished
run_id / answer_id / conversation_id
graph_version / node / operation
duration_ms / step_count
model_config_id（如调用模型）
retrieval_run_id（如调用检索）
input_token_count / output_token_count
degradation_flags / error_code
```

不得记录完整问题、完整上下文、证据正文和模型密钥。需要调试正文时使用受控、短期、显式开启的脱敏采样机制，V1 默认关闭。

### 17.2 指标

- `agent_runs_total{status,operation,graph_version}`；
- `agent_node_duration_seconds{node}`；
- `agent_step_limit_total`；
- `agent_recovery_total{node}`；
- `agent_query_rewrite_total`；
- `agent_citation_repair_total`；
- `agent_memory_compaction_total{status}`；
- `agent_context_tokens`；
- `agent_answer_latency_seconds`；
- `agent_route_total{operation,requires_retrieval}`。

告警建议：失败率、超时率、step limit、checkpoint 写失败率、P95 延迟和 memory update 持续失败。

## 18. 测试设计

### 18.1 单元测试

| 编号 | 场景 | 断言 |
|---|---|---|
| TC-LG-001 | `CHAT` 路由 | 不调用 RetrievalService |
| TC-LG-002 | 产品问题路由 | 必须进入 retrieve |
| TC-LG-003 | 一般概念 EXPLAIN | 可不检索 |
| TC-LG-004 | 带产品实体 EXPLAIN | 必须检索 |
| TC-LG-005 | 意图 Schema 两次失败 | 只修复一次并保守路由 |
| TC-LG-006 | 上下文预算 | 不超过配置，保留完整问答轮次 |
| TC-LG-007 | 指代消解上下文 | 相关实体轮次优先保留 |
| TC-LG-008 | 引用不在 evidence | 校验失败 |
| TC-LG-009 | query rewrite 上限 | 最多一次 |
| TC-LG-010 | citation repair 上限 | 最多一次 |
| TC-LG-011 | memory update 失败 | 答案成功且有降级标志 |
| TC-LG-012 | step limit | 终止为明确错误，无死循环 |

### 18.2 图集成测试

| 编号 | 场景 | 断言 |
|---|---|---|
| TC-LG-101 | 问候 | 生成一般回答、无 retrieval run、无 citations |
| TC-LG-102 | 内部产品问题 | 检索、生成、引用、持久化完整 |
| TC-LG-103 | 输入不足 | 返回澄清问题，不检索 |
| TC-LG-104 | 部分证据 | 只回答已知部分并显示依据不足 |
| TC-LG-105 | 来源冲突 | 并列冲突来源，不擅自裁决 |
| TC-LG-106 | 无证据 | 不生成内部事实、不产生虚假引用 |
| TC-LG-107 | 检索完成后模拟崩溃 | 恢复后不重复检索 |
| TC-LG-108 | 持久化后模拟 Worker 重试 | Answer/Citation 不重复 |
| TC-LG-109 | 用户取消 | 不继续生成，状态 CANCELED |
| TC-LG-110 | 同会话连续追问 | 能解析上一轮实体，同时本轮重新检索事实 |
| TC-LG-111 | 长会话 | 自动压缩，输入不超模型窗口 |
| TC-LG-112 | checkpoint 不可用 | 明确失败或按策略回退，无静默数据丢失 |

### 18.3 回归测试

- 现有 conversation API 测试全部通过；
- 现有 answer worker、SSE、retrieval 和 model gateway 测试全部通过；
- 发送消息的 HTTP 状态、Answer 状态机和引用 Schema 不变；
- 文档分类、导入、OpenSearch 索引和模型配置不受影响；
- 切换会话只读取已持久化数据，不等待后台图执行；
- 来源引用默认折叠和原文定位由前端 E2E 覆盖。

## 19. 实施顺序

实现 Agent 必须按以下顺序提交，避免一次性替换后无法定位问题。

### 阶段 A：基础设施，不切流

1. 加入有界依赖并生成锁文件；
2. 新增 `agent` 包、状态 DTO、错误和设置；
3. 增加 `conversation_memories`、`agent_runs` 迁移和模型；
4. 配置 PostgresSaver 与独立 schema；
5. 编写最小图编译、checkpoint 读写和恢复测试；
6. `agent_graph_enabled=false`，生产行为不变。

### 阶段 B：节点化复用现有能力

1. 从 `qa/worker.py` 提取上下文、路由、生成和持久化为节点服务；
2. `retrieve` 只适配现有 RetrievalService；
3. `generate_*` 只适配 model gateway；
4. 加入确定性引用校验；
5. 完成无 checkpoint 的纯图集成测试。

### 阶段 C：记忆和恢复

1. 实现 token 估算与上下文预算；
2. 实现 ConversationMemory 读取、压缩和乐观锁；
3. 接入 PostgresSaver；
4. 注入故障验证检索后恢复、生成后恢复和幂等持久化；
5. 加入 checkpoint 清理任务。

### 阶段 D：灰度切换

1. 开发/测试环境开启 feature flag；
2. 可选 shadow 模式只比较旧、新路由，不重复生成或写业务结果；
3. 对黄金问题集比较是否检索、证据、引用、延迟和 token 成本；
4. 小范围启用新图；
5. 观察失败率、超时、引用修复和会话切换性能；
6. 达到验收门槛后全量开启。

### 阶段 E：清理旧编排

1. feature flag 稳定至少一个发布周期；
2. 删除 `qa/worker.py` 中重复的条件分支，只保留薄适配器；
3. 保留回滚版本所需配置和数据库兼容期；
4. 更新 DD-07、DD-10、DD-15 和运维文档的实现状态。

## 20. 回滚方案

- 关闭 `agent_graph_enabled`，新任务走旧 Worker 编排；
- 已在 LangGraph 中运行的 answer 按 `graph_version` 继续完成或取消，不把同一 answer 同时交给两套编排；
- 新增业务表保留，不做紧急 down migration；旧路径可以忽略它们；
- checkpoint 可以停止写入并延后清理，不影响业务答案；
- 回滚不得删除已生成的 Message、Answer 和 Citation；
- 若数据库迁移本身失败，在应用切流前回滚迁移并保持 flag 关闭。

## 21. 交付给实现 Agent 的任务清单

实现 Agent 收到本文后，应逐项完成并在交付说明中引用编号：

- [ ] LG-IMP-001：确认工作树用户改动并避免覆盖；
- [ ] LG-IMP-002：锁定 LangGraph 依赖并验证 Python 3.11/3.12；
- [ ] LG-IMP-003：实现 AgentState 与 RuntimeContext；
- [ ] LG-IMP-004：新增 ConversationMemory 与 AgentRun 数据模型和迁移；
- [ ] LG-IMP-005：实现 PostgresSaver 工厂、schema 和保留策略；
- [ ] LG-IMP-006：实现主图全部节点和条件边；
- [ ] LG-IMP-007：复用 RetrievalService，不复制检索逻辑；
- [ ] LG-IMP-008：复用 model_gateway，不直连服务商 SDK；
- [ ] LG-IMP-009：实现 token 预算和滚动记忆；
- [ ] LG-IMP-010：实现引用校验和有界修复；
- [ ] LG-IMP-011：实现 Worker 薄适配器和 checkpoint 恢复；
- [ ] LG-IMP-012：保持 API/SSE 向后兼容；
- [ ] LG-IMP-013：加入 feature flag、指标、结构化日志和清理任务；
- [ ] LG-IMP-014：完成 TC-LG-001～112；
- [ ] LG-IMP-015：执行现有回归测试和黄金问题集；
- [ ] LG-IMP-016：提交迁移、回滚、配置和运维说明。

禁止事项：

- 不得以“LangGraph 更方便”为由重写检索或模型配置系统；
- 不得引入开放式无限 ReAct 循环；
- 不得用 checkpoint 替换 messages/answers/citations；
- 不得把会话摘要当作内部产品事实；
- 不得在一个数据库事务中调用远程模型或 OpenSearch；
- 不得把 API Key、完整提示词或文档正文写入 AgentRun 日志；
- 不得删除或回退工作树中与本任务无关的现有改动。

## 22. 验收标准

| 编号 | 验收项 |
|---|---|
| AC-LG-001 | “你好”不调用知识库，内部产品问题必须调用知识库 |
| AC-LG-002 | Agent 能在同一会话解析最近上下文和用户约束 |
| AC-LG-003 | 长会话按 token 预算压缩，不再固定只取 6 条 |
| AC-LG-004 | 内部事实没有有效证据时不生成确定性结论 |
| AC-LG-005 | 引用全部来自本轮 evidence，原文地址不是模型生成 |
| AC-LG-006 | query rewrite、引用修复和总图步数均有硬上限 |
| AC-LG-007 | 进程在检索后崩溃，重试能从 checkpoint 恢复且不重复检索 |
| AC-LG-008 | Worker 重复投递不会产生重复答案或引用 |
| AC-LG-009 | 记忆更新失败不影响已验证答案，并可观测降级 |
| AC-LG-010 | 新旧路径可由 feature flag 切换，回滚不丢业务数据 |
| AC-LG-011 | 现有 API、SSE、RAG 和模型网关回归测试通过 |
| AC-LG-012 | 每次 AgentRun 可查看节点耗时、操作、步数和错误码，但不泄露正文或密钥 |

只有 AC-LG-001～012 全部通过，才允许删除旧手写编排。

## 23. 未决项与默认处理

| 未决项 | 默认处理 | 关闭条件 |
|---|---|---|
| 模型实际上下文窗口如何读取 | 从模型配置增加能力字段，缺失时使用保守默认 | 每个可启用模型完成窗口配置 |
| checkpoint 与业务库是否同实例 | 可同实例、独立 schema 和账号 | 运维确认连接池和容量 |
| 是否需要跨会话长期记忆 | V1 不实现 | 完成隐私、授权和产品需求评审 |
| shadow 流量成本 | 默认只比较路由，不双生成答案 | 测试环境成本评估完成 |
| checkpoint 保留期 | 成功 14 天，失败 30 天建议值 | 运维和合规确认 |
| SSE 是否增加节点级阶段 | 可增加且前端兼容未知枚举 | 前后端联调确认 |

## 24. 可直接交给实现 Agent 的启动指令

下面的文本可以与本文一起交给编码 Agent。本文仍是最高优先级的实现契约，启动指令不能替代具体章节。

```text
你需要在 AE Knowledge Platform 中按照 DD-21 实现 LangGraph 知识助手重构。

开始前：
1. 阅读仓库 AGENTS.md、DD-07、DD-10、DD-15、DD-19、DD-20 和 DD-21；
2. 检查 git status，列出用户已有改动，不得回退或覆盖无关内容；
3. 核对 conversation/service.py、worker/runner.py、worker/pipeline.py、
   qa/worker.py、qa/llm.py、retrieval/service.py 和 model_gateway 的真实接口；
4. 先给出“现有接口 → 新节点”的映射，再开始修改。

实现要求：
- 使用 LangGraph StateGraph，不使用开放式 AgentExecutor；
- LangGraph 只负责编排，必须复用 RetrievalService 和 model_gateway；
- PostgreSQL messages/answers/citations 是业务事实源；
- checkpoint 使用 answer_id 作为 thread_id，只用于恢复；
- 实现 token 预算、滚动会话记忆和有界循环；
- 保持现有 HTTP/SSE 兼容；
- 使用 agent_graph_enabled 分阶段切换；
- 不在远程调用期间持有数据库事务；
- 所有最终写入必须幂等；
- 内部事实无证据时不得生成确定性答案。

实施顺序严格遵循 DD-21 第 19 节。每完成一个阶段：
1. 运行该阶段最窄单元和集成测试；
2. 记录实际修改文件、迁移 head、配置项和测试结果；
3. 对照 LG-IMP 和 AC-LG 编号说明完成情况；
4. 如发现现有代码与文档冲突，先报告证据、影响和最小调整方案，
   不得静默改变业务不变量。

最终交付必须包括：
- 代码与数据库迁移；
- 配置示例和 checkpoint 初始化/清理说明；
- TC-LG-001～112 对应测试；
- 现有会话、SSE、RAG、模型网关回归结果；
- feature flag 开启、灰度和回滚操作；
- 未完成项、风险和后续评测建议。
```

## 25. 参考资料

- LangGraph Overview：<https://docs.langchain.com/oss/python/langgraph/overview>
- LangGraph Persistence：<https://docs.langchain.com/oss/python/langgraph/persistence>
- LangGraph Memory：<https://docs.langchain.com/oss/python/langgraph/add-memory>
- LangGraph Workflows and Agents：<https://docs.langchain.com/oss/python/langgraph/workflows-agents>
- LangGraph PyPI：<https://pypi.org/project/langgraph/>

本文中的外部 API 骨架用于约束设计。实现时以锁定版本的官方文档和编译测试为准，但不得改变本文的业务不变量、边界和验收标准。
