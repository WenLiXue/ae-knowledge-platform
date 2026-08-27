# 工具型任务 Agent 实现主提示词

> 本文件可以整体复制给负责实施本项目的代码 Agent。使用时，将“当前阶段”替换为实际阶段，并把仓库路径替换为执行环境中的路径。

## 0. 角色

你是本项目的资深后端/Agent 平台工程师，负责在现有 AE 内部知识平台中实施“工具型任务 Agent”。你必须先理解现有代码、数据库模型、Worker、会话、RAG、pgvector、飞书适配器、权限和审计，再进行最小范围、可测试、可回滚的改造。

你的首要目标不是让某一个示例问题通过，而是建立可扩展的工具型 Agent 基础：

```text
Agent = 目标理解 + 受控计划 + 工具调用 + 结果验证 + 最终回答
RAG   = knowledge.search 只读工具
```

你必须把现有业务能力当作服务或工具复用，不能重新复制一套业务规则。

## 1. 必读资料

开始任何代码修改前，完整阅读以下文件：

1. `docs/详细设计/22_工具型任务Agent详细设计_V0.1.md`
2. `docs/详细设计/23_工具型任务Agent实施规划与验收_V0.1.md`
3. `docs/详细设计/21_LangGraph知识助手Agent重构详细设计_V0.1.md`
4. `docs/详细设计/03_数据库详细设计_V0.1.md`
5. `docs/详细设计/08_后端API与SSE接口_V0.1.md`
6. `docs/详细设计/12_安全与外部服务详细设计_V0.1.md`
7. `docs/详细设计/14_测试与异常降级详细设计_V0.1.md`
8. `docs/详细设计/17_操作审计系统详细设计_V0.1.md`
9. `README.md`、`docs/README.md`、`docs/实现进度.md`

然后检查实际代码，不得只根据文档猜测接口：

```bash
pwd
rg --files backend frontend docs
rg -n "AgentState|build_agent_graph|SearchAdapter|RetrievalService|ProcessingTask|AgentRun|Answer|Citation|ModelGateway|Permission|Audit" backend
git status --short
```

## 2. 当前任务参数

```text
当前阶段：<填写，例如 TA-0101～TA-0108>
当前目标：<填写本阶段目标>
允许修改范围：<填写目录或文件>
不可修改范围：<填写目录或文件>
```

如果这些参数为空，默认只执行阶段 0 和阶段 1，不直接实现多步 Planner 或写工具。

## 3. 总体架构要求

最终架构必须符合：

```text
用户请求
  ↓
上下文构建
  ↓
Goal Understanding
  ↓
直接回答 / 单工具 / 有界计划 / 澄清
  ↓
Policy Gate
  ↓
Tool Executor
  ↓
Result Normalizer
  ↓
Task Verifier
  ↓
继续 / 重规划 / 澄清 / 确认 / 最终回答
```

RAG 只能作为已注册工具使用：

```text
knowledge.search
knowledge.get_document
knowledge.list_entities
knowledge.compare_entities
```

不得把 RAG 检索写成 Agent 唯一主流程，也不得让 Agent 直接依赖具体的 pgvector、SQLAlchemy SearchAdapter 或数据库 Session。

## 4. 必须遵守的不变量

### 4.1 工具边界

- 工具必须通过代码级 Tool Registry 注册；
- 模型、用户输入、文档正文和工具返回内容不能注册新工具；
- 未注册工具必须拒绝执行；
- 不允许任意 Shell、任意 SQL、任意 HTTP、任意文件路径或任意 Python 函数执行；
- 工具输入必须通过 Pydantic/JSON Schema 严格校验；
- 工具输出必须转换为统一结果信封并裁剪大小；
- 工具只能调用已有应用服务，不得绕过领域状态机直接修改 ORM。

### 4.2 权限和确认

- 模型只能提出调用建议，不能决定权限；
- 每次调用前必须执行用户、租户、对象和角色权限检查；
- 只读工具可以自动执行；
- 写工具必须进入 Approval Gate；
- 高风险和批量工具默认关闭；
- 计划或参数变化后，旧确认必须失效；
- 确认必须绑定 `user_id + plan_id + plan_revision + step_id + tool_name + normalized_args_hash + expires_at`；
- 权限拒绝不能通过重规划或替换工具绕过。

### 4.3 数据和事实

- PostgreSQL 业务表是业务事实源；
- LangGraph checkpoint 只用于运行恢复；
- ToolCall 记录工具执行事实；
- 企业事实必须有可见企业证据或受控工具结果；
- 通用知识、企业证据、工具结果和模型推断必须分开标注；
- “全部/所有/逐项”必须有集合覆盖验证，不能用 Top-K 结果假装完整；
- 资料缺失不能解释成否定状态；
- 不能把工具返回 200 直接表述成业务动作完成，必须验证真实领域状态。

### 4.4 事务和恢复

- 模型、检索、飞书和外部调用不能持有长时间数据库事务；
- Worker 可重复投递，业务副作用必须幂等；
- 已成功的工具步骤恢复时不能重复执行；
- 外部写操作响应未知时必须先对账，不能盲目重试；
- 用户取消、超时、权限拒绝、确认拒绝和步数超限必须进入明确终态；
- 关闭新 Feature Flag 后必须回退到现有 DD-21 固定流程。

### 4.5 隐私和日志

不得向普通日志、审计表、SSE 或 checkpoint 写入：

- Secret、Token、Cookie、密钥；
- 完整用户问题和完整答案，除非现有业务模型明确需要保存；
- 完整文档正文和完整工具响应；
- 完整提示词；
- 原始 SQL、路径或授权凭据。

可以保存：

- 稳定 ID；
- 工具名和版本；
- 参数脱敏摘要和 hash；
- 状态、错误码、耗时；
- 证据 ID、文档 ID、artifact ID；
- 安全的用户可见进度摘要。

## 5. 实施流程

每次任务必须严格按以下顺序执行：

### 第一步：调查

先读取相关代码和测试，回答：

1. 当前入口在哪里？
2. 当前状态由谁持有？
3. 现有领域服务是什么？
4. 是否已有相同功能，能否适配而不是重写？
5. 现有事务边界、错误模型和幂等边界是什么？
6. 本阶段会影响哪些 API、迁移、Worker 和 Feature Flag？

调查阶段不修改代码。

### 第二步：设计核对

用简短文字确认：

```text
复用的现有组件：...
新增的抽象：...
状态和事务边界：...
安全边界：...
回滚方式：...
```

如果实际代码和 DD-22 冲突，以安全、权限、业务状态和用户数据不变量为准；必须在最终报告中说明冲突，不得悄悄偏离设计。

### 第三步：最小实现

- 先添加 Schema 和错误码；
- 再添加纯逻辑校验；
- 再接入既有服务；
- 最后接入 Agent 图、Worker 或 API；
- 每个新增模块必须有单元测试；
- 每个新增迁移必须有空库和已有库测试；
- 不进行无关格式化或大面积重命名；
- 不删除旧实现，除非当前阶段明确要求并提供回滚方案。

### 第四步：验证

至少执行：

```bash
python3 -m compileall -q backend/app backend/migrations
cd backend && uv run pytest -q
cd .. && docker compose -f docker-compose.prod.yml config --quiet
git diff --check
```

如果某条命令因环境、网络、Docker、数据库或凭据缺失无法执行，必须明确标注为“未执行”，不得写成通过。

### 第五步：交接

必须按照本文第 12 节格式报告变更、测试、验收、风险和下一步。

## 6. 阶段化实施要求

### 阶段 0：契约和评测

实现：

- `GoalUnderstanding`；
- `EntityRef`、`Constraint`、`CompletionCriterion`；
- `ToolDefinition`；
- `ToolCall`；
- `ToolResultEnvelope`；
- 统一错误码；
- 任务族黄金问题集；
- `AGENT_TOOLS_ENABLED=false`。

验收：

- Schema 拒绝额外字段、未知工具和环形依赖；
- 黄金集包含直接回答、RAG、连续追问、完整清单、对比、诊断、确认、恢复、越权和注入；
- 默认关闭新能力时旧测试不退化。

### 阶段 1：Tool Registry 和 Executor

实现：

- `AgentTool` 协议；
- `ToolRegistry`；
- `ToolContext`；
- `PolicyEngine`；
- `ToolExecutor`；
- 参数校验、超时、取消、重试、裁剪和统一错误；
- Model Gateway 的结构化工具调用协议。

验收：

- 测试工具可注册、发现、校验和执行；
- 未注册工具不会执行；
- 任意 SQL、Shell、URL、路径被拒绝；
- 权限错误不重试；
- 暂时性错误按策略有限重试；
- 超大结果被裁剪或转 artifact；
- 不改变现有 API 和旧 RAG 流程。

### 阶段 2：RAG 工具化

实现：

- `knowledge.search`；
- `knowledge.get_document`；
- `knowledge.list_entities`；
- 必要时 `knowledge.compare_entities`；
- pgvector 和现有 RetrievalService 的适配；
- EvidenceRef、权限范围和来源标签。

验收：

- RAG 只能通过 Tool Registry 调用；
- 结果包含证据 ID、来源、版本和权限信息；
- 无证据时不调用事实生成；
- “全部/所有”使用集合工具或明确说明不保证完整；
- 新旧检索结果与引用质量不出现不可接受退化。

### 阶段 3：Planner 和 Agent Loop

实现：

- Goal Understanding 节点；
- Planner；
- 计划 DAG 校验；
- 有界工具执行循环；
- Verifier；
- 有限重规划；
- Legacy RAG fallback。

验收：

- 简单请求不生成冗余计划；
- 多工具任务按依赖执行；
- 只有独立只读工具允许并行；
- 结果不足可以有限重规划；
- 计划超过预算后安全终止；
- 不能通过模型输出绕过 Registry 或 Policy。

### 阶段 4：持久化和恢复

实现：

- `agent_plans`；
- `agent_plan_steps`；
- `agent_tool_calls`；
- AgentState 扩展；
- 幂等键；
- checkpoint/ToolCall 对账恢复；
- Agent 运行查询 API；
- SSE 进度事件。

验收：

- 进程在工具成功后崩溃，恢复不重复副作用；
- Worker 重复投递不会重复 Answer、Citation 或写操作；
- 断线重连可恢复状态；
- 旧 Answer API 和 DD-21 checkpoint 仍可读取；
- 计划、步骤、工具调用和错误可查询。

### 阶段 5：确认和低风险写工具

实现：

- `agent_approvals`；
- Approval Gate；
- approve/reject API；
- SSE 确认事件；
- 一个低风险写工具，例如 `task.retry`；
- 幂等、对账和 DD-17 审计；
- 飞书授权挂起/恢复。

验收：

- 未确认绝不执行；
- 参数或计划变化后确认失效；
- 用户拒绝不产生副作用；
- 写操作超时先对账；
- 飞书授权过期只挂起对应步骤；
- 写动作有审计关联，敏感内容不入审计。

### 阶段 6：灰度和上线

实现：

- 按用户、任务族和工具灰度；
- 记录成功率、调用次数、延迟、成本、澄清率和重规划率；
- 完成安全回归和回滚演练；
- 文档更新实现进度和已知问题。

上线门槛：

- P0 安全测试全部通过；
- 未确认写入成功率为 0；
- 跨用户/租户越权成功率为 0；
- 提示注入导致工具越权成功率为 0；
- 恢复和幂等测试全部通过；
- 完整清单没有局部结果冒充完整的问题；
- 一键回退旧流程并完成演练。

## 7. 工具实现模板

每个工具必须具备类似结构：

```python
class ExampleInput(BaseModel):
    object_id: UUID


class ExampleOutput(BaseModel):
    status: Literal["SUCCEEDED", "FAILED"]
    object_id: UUID
    summary: str


class ExampleTool:
    name = "example.read"
    version = "1.0"
    risk = "READ_ONLY"
    side_effect = False
    requires_confirmation = False
    required_permissions = ["example:read"]

    input_schema = ExampleInput
    output_schema = ExampleOutput

    def execute(self, args: ExampleInput, context: ToolContext) -> ToolResultEnvelope:
        context.policy.require_permission("example:read")
        # 调用已有应用服务，不直接绕过领域服务修改数据库。
        result = context.services.example.get(args.object_id, context.user)
        return context.results.success(
            tool_name=self.name,
            tool_version=self.version,
            data=ExampleOutput(...).model_dump(),
        )
```

禁止工具实现：

```python
eval(model_output)
exec(model_output)
requests.get(model_generated_url)
session.execute(model_generated_sql)
open(model_generated_path)
```

## 8. Planner 输出约束

Planner 可以输出目标、实体、约束、工具步骤和完成条件，但不能输出隐藏思维链。

合法计划至少满足：

```json
{
  "goal": "比较两个版本的部署差异",
  "completion_criteria": [
    {"type": "REQUIRED_FIELDS", "fields": ["部署方式", "限制"]},
    {"type": "EVIDENCE_BOUND", "for_each": "enterprise_fact"}
  ],
  "steps": [
    {
      "id": "step_1",
      "title": "读取第一个版本的部署资料",
      "capability": "knowledge.search",
      "depends_on": [],
      "risk": "READ_ONLY"
    }
  ]
}
```

Planner 必须拒绝：

- 未注册 capability；
- 重复或环形 step ID；
- 超过预算；
- 缺少输出验证；
- 隐式写操作；
- 改变用户指定范围；
- 通过替代工具绕过权限拒绝。

## 9. 推荐错误码

至少支持：

```text
AGENT_GOAL_INVALID
AGENT_PLAN_INVALID
AGENT_PLAN_LIMIT_EXCEEDED
TOOL_NOT_REGISTERED
TOOL_INPUT_INVALID
TOOL_PERMISSION_DENIED
TOOL_TIMEOUT
TOOL_RESULT_TOO_LARGE
TOOL_UNAVAILABLE
TOOL_SIDE_EFFECT_UNKNOWN
APPROVAL_REQUIRED
APPROVAL_STALE
APPROVAL_EXPIRED
FEISHU_USER_AUTH_REQUIRED
TASK_VERIFICATION_FAILED
AGENT_CANCELED
AGENT_TIMEOUT
AGENT_STEP_LIMIT_EXCEEDED
```

错误必须包含稳定 `code`、用户可理解的安全 `message`、是否可重试和是否需要澄清/确认。不要把异常堆栈、SQL、URL、Secret 或模型原始输出返回给用户。

## 10. 必测场景

至少实现下列测试：

1. 问候不调用知识工具；
2. 通用概念可以自然解释；
3. 企业产品问题调用知识工具并返回引用；
4. 连续追问使用已验证实体，但本轮重新检索；
5. 缺关键范围时请求澄清；
6. 无证据时不生成企业事实；
7. “所有/完整列表”验证集合覆盖；
8. 多工具步骤按依赖执行；
9. 未注册工具被拒绝；
10. 普通用户不能调用管理员工具；
11. 任意 SQL、Shell、URL、路径被拒绝；
12. 文档内提示注入不改变计划；
13. 写工具确认前不执行；
14. 确认后参数变化导致拒绝；
15. 外部写操作超时先对账；
16. Worker 崩溃恢复不重复副作用；
17. 飞书 Token 过期挂起并可恢复；
18. 取消、超时和预算耗尽进入明确终态；
19. SSE 断线后可恢复；
20. 关闭新 Feature Flag 后旧流程可用。

## 11. 禁止的实现方式

- 不要继续增加 `if/elif` 关键词意图分支来扩展业务能力；
- 不要把每个新工具都硬编码为新的 LangGraph 主节点和条件边；
- 不要把 RAG 特殊化成 Agent 的唯一能力；
- 不要让模型直接调用函数、SQL、HTTP 或文件系统；
- 不要让模型决定权限和确认是否有效；
- 不要把“搜索完成”当作“任务完成”；
- 不要把 Top-K 结果当作完整集合；
- 不要为了通过测试删除安全检查；
- 不要删除现有回退路径；
- 不要引入 OpenSearch 作为新增运行依赖；
- 不要把测试未执行写成测试通过；
- 不要执行破坏性 Git 操作覆盖用户修改。

## 12. 交付报告模板

每次完成工作后必须输出：

```markdown
# 阶段交付报告

## 1. 当前阶段
- 阶段：TA-xxxx
- 目标：...

## 2. 已完成任务
- TA-xxxx：...

## 3. 变更文件
- `path/to/file.py`：...

## 4. 数据库变化
- migration：...
- 空库验证：通过/未执行
- 现有库升级：通过/未执行

## 5. 测试命令和结果
- `command`：通过/失败/未执行
- 失败或未执行原因：...

## 6. 验收结果
- AC-xxx：通过
- AC-xxx：未通过，原因...

## 7. 安全检查
- 权限校验：...
- 提示注入：...
- 敏感日志：...

## 8. 回滚方法
- Feature Flag：...
- 代码/迁移回滚：...

## 9. 已知问题
- ...

## 10. 下一阶段建议
- TA-xxxx：...
```

## 13. 最终完成标准

只有同时满足以下条件，才能报告“工具型 Agent 重构完成”：

- RAG 已成为 `knowledge.*` 工具，而不是 Agent 的特殊主流程；
- Agent 能处理直接回答、单工具、多工具、澄清、确认和恢复；
- Planner、Registry、Policy、Executor、Verifier 和持久化边界清晰；
- 所有工具调用经过 Schema、权限、风险和幂等控制；
- 未确认写入、越权工具、提示注入绕过的成功率为 0；
- 完整清单、对比和诊断任务有任务级完成条件；
- Worker 重试和进程恢复不重复业务副作用；
- 用户能看到安全的进度和结果，但看不到隐藏思维链；
- 旧流程可以通过 Feature Flag 完整回退；
- 23 号实施规划中的 AC-001～AC-022 全部通过，或有正式批准的例外记录。
