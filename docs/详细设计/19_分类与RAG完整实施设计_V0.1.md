# AE 内部知识平台——文档分类与 RAG 完整实施设计

版本：V0.1  
状态：待实现  
文档编号：DD-19  
日期：2026-08-25  
目标工程：`D:\Projects\ae-knowledge-platform`  
依赖设计：DD-02、DD-03、DD-04、DD-05、DD-06、DD-07、DD-08、DD-10、DD-14、DD-15

## 1. 文档目的

本文是可直接交给实现 Agent 的工程实施基线，覆盖：

1. 统一文档类型目录；
2. 实现真实文档解析、分类、切片、Embedding 和索引；
3. 实现混合检索、Rerank、证据选择和降级；
4. 实现会话、问答、引用、反馈与 SSE；
5. 将当前前端 Mock 替换为真实后端 API；
6. 建立分类与 RAG 的测试、评测、可观测性和上线门槛。

本文不授权一次性大改。实现必须按阶段提交，每一阶段具有独立迁移、测试和回滚边界。

## 2. 当前实现证据

### 2.1 已存在能力

- 飞书文档发现、提交和真实/模拟正文读取适配器；
- 数据库任务表、`FOR UPDATE SKIP LOCKED` 领取、租约、心跳、重试和 Attempt；
- `FETCH → PARSE → CLASSIFY → CHUNK → EMBED → INDEX → FINALIZE` 阶段骨架；
- 来源与版本状态、最终版本原子切换；
- 产品、版本、文档类型、产品形态、来源优先级和 LLM 配置 API；
- OpenAI-compatible LLM 连接测试；
- 查询和会话前端页面、答案块和引用的前端类型。

### 2.2 当前 Mock/缺口

- `PARSE` 只写假的 `parsed_object_key`；
- `CLASSIFY` 只按 `canonical_key` 是否包含 `uncertain/irrelevant` 判定；
- `CHUNK` 不写 Chunk；
- `EMBED` 只记录 `mock-embedding/384`；
- `INDEX` 只记录假的 generation；
- 数据库没有分类结果、文档元数据、Chunk、会话、答案、引用、检索运行等实体；
- 后端没有 conversation、answer、retrieval 或 SSE 路由；
- `frontend/src/api/conversations.ts` 全部使用浏览器内存 Mock；
- 前端 Mock 文档类型与数据库目录不一致；
- 当前来源可进入 `QUERYABLE`，但没有真实 Chunk 或索引，这是必须优先关闭的状态语义风险。

### 2.3 实施约束

- 保留现有认证、飞书、审计、系统日志和配置能力；
- 保留用户未提交的前端布局修改；
- 不在 API 请求线程执行解析、分类、Embedding、索引或答案生成；
- 外部模型、Embedding、Rerank 和检索引擎必须通过适配器调用；
- 正文按不可信数据处理，不执行其中的指令、链接、宏或脚本；
- 产品事实只能由可追溯证据支持，不允许模型记忆补全；
- V1 保持模块化单体，不拆微服务，不引入通用自治 Agent 框架。

## 3. 目标架构与边界

```text
文档提交 API
  → ProcessingTask
  → FETCH
  → PARSE
  → CLASSIFY（Model Gateway）
  → CHUNK
  → EMBED（Embedding Gateway）
  → INDEX（Search Adapter staging generation）
  → VERIFY
  → FINALIZE（原子切换 current_version）

用户消息 API
  → 创建 Answer + ANSWER_GENERATE Task
  → Query Planner（Model Gateway）
  → Retrieval Service
      → BM25
      → Query Embedding / Vector
      → RRF Fusion
      → Rerank（可降级）
      → Evidence Selection
  → Answer Generator（Model Gateway）
  → Citation Validator
  → 持久化 Answer/Citation
  → SSE 从数据库事件/状态输出
```

职责边界：

- Classification Service：只返回经过 Schema 校验的候选分类，不改业务状态；
- Retrieval Service：只返回证据候选与分数，不生成答案；
- QA Application Service：编排查询计划、检索、生成、引用校验和持久化；
- Worker：执行可恢复任务，不承担 HTTP 会话；
- API：鉴权、校验、创建命令、读取状态和输出 SSE；
- Model Gateway：屏蔽供应商协议，统一超时、错误、用量和响应校验。

## 4. 统一文档类型目录

### 4.1 正式目录

| sort | code | 名称 | 典型内容 |
|---:|---|---|---|
| 10 | `product-spec` | 产品规格 | 硬件规格、参数表、型号清单 |
| 20 | `product-whitepaper` | 产品白皮书 | 产品定位、架构、能力总览 |
| 30 | `requirement` | 需求说明书 | 产品或项目需求 |
| 40 | `design` | 设计文档 | 概要设计、详细设计、开发设计 |
| 50 | `deployment-guide` | 部署说明 | 安装、部署、升级、环境要求 |
| 60 | `operation-manual` | 操作手册 | 配置、使用、运维步骤 |
| 70 | `test-report` | 测试报告 | 测试范围、过程和结论 |
| 80 | `fault-analysis` | 故障分析 | 故障定位、原因和处理办法 |
| 90 | `seg-case` | SEG 问题案件 | 客户问题、处理过程和关闭结论 |
| 100 | `compatibility-list` | 兼容性清单 | 操作系统、版本、硬件兼容矩阵 |
| 110 | `release-note` | 版本说明 | 发布说明、变更点、已知问题 |
| 999 | `other` | 其他资料 | 明确相关但无法归入已知类型 |

### 4.2 概念分离

- `source_type/resource_type`：文件或外部载体，如 `FEISHU_WIKI`、`FEISHU_DOCX`、`PDF`、`DOCX`、`XLSX`；
- `document_type_code`：业务语义，如产品规格、测试报告、SEG 案件；
- `document_type_code` 未知不等于相关性不确定；相关性明确时允许 `other` 或 `null + missing_fields`；
- 分类模型只能输出数据库当前启用的稳定 code，禁止自由生成新类型。

### 4.3 目录迁移

新增 Alembic 迁移，父 revision 使用执行时真实 head，不修改旧迁移。

升级策略：

1. 保留 `requirement/design/fault-analysis/test-report` 的主键和 code，更新名称、说明、顺序；
2. 将现有 `manual` 原位迁移为 `operation-manual`。迁移前必须检查是否已有引用；如已有引用，先更新引用表再修改 code；
3. 以固定 UUID 插入其余 7 个类型；
4. 使用 `INSERT ... ON CONFLICT (code) DO UPDATE`，使开发库重复数据可收敛；
5. 不删除管理员新增类型；未纳入正式基线的已有类型改为 `DISABLED` 前必须输出审计/迁移日志；
6. downgrade 只删除本迁移新增且未被引用的记录，并将 `operation-manual` 恢复为 `manual`；若存在引用则 downgrade 明确失败，不静默破坏数据。

### 4.4 前端目录

- `QueryComposer` 调用 `listCatalogProducts()` 和 `listCatalogDocumentTypes()`；
- 选择产品后调用 `listCatalogVersions(productId)`；
- 删除 `CATALOG_OPTIONS` 中产品、版本、文档类型的业务依赖；
- 加载失败时保留问题输入，筛选区展示错误和重试；
- 不回退到另一套 Mock code；
- 已选择的目录项在刷新过程中继续显示已有名称快照或稳定 code；
- 请求使用 AbortController，卸载后不更新状态；
- 产品变化必须清空版本；禁用/不存在的历史筛选值按“已停用”展示但不用于新选择。

## 5. 数据模型与迁移

所有新表使用 PostgreSQL schema、UUID、`created_at/updated_at`、必要索引和 FK。迁移需与 ORM 同步。

### 5.1 `knowledge.classification_results`

- `id uuid PK`
- `version_id uuid FK document_versions`
- `status varchar(32)`：`RUNNING/VALID/SUPERSEDED/FAILED`
- `relevance varchar(32)`：`RELEVANT/IRRELEVANT/UNCERTAIN`
- `relevance_confidence numeric(5,4)`
- `output_json jsonb`
- `evidence_json jsonb`
- `missing_fields text[]`
- `reason_summary text`
- `model_key/model_revision/prompt_revision/input_builder_revision varchar`
- `classification_config_revision bigint`
- `input_hash char(64)`
- `token_usage_json jsonb`
- `error_code/error_summary varchar/text`
- 唯一约束：`UNIQUE(version_id, input_hash)`；
- 索引：`(version_id, status)`、`(relevance, created_at)`。

### 5.2 `knowledge.document_metadata`

- `version_id uuid PK/FK`
- `classification_result_id uuid nullable FK`
- `product_id uuid nullable FK`
- `product_version_id uuid nullable FK`
- `document_type_id uuid nullable FK`
- `product_form_id uuid nullable FK`
- `is_domestic boolean nullable`
- `module_name/business_topic/summary text nullable`
- `keywords text[]`
- `field_sources jsonb`：每字段 `MODEL/MANUAL/INFERRED`；
- `field_confidence jsonb`
- `updated_by_user_id uuid nullable`
- 业务校验：版本必须属于产品；未知布尔值保持 null。

### 5.3 `knowledge.document_chunks`

- `id uuid PK`
- `version_id uuid FK`
- `ordinal integer`
- `chunk_type varchar(32)`：`paragraph/list/table/sheet_region`
- `content text`
- `content_sha256 char(64)`
- `heading_path text[]`
- `locator_json jsonb`
- `metadata_snapshot jsonb`
- `token_count integer`
- `embedding_status varchar(32)`
- `created_at`
- 唯一约束：`UNIQUE(version_id, ordinal)`；
- 索引：`(version_id)`、`(content_sha256)`。

### 5.4 会话和答案

新增：

- `conversation.conversations`
- `conversation.messages`
- `conversation.answers`
- `conversation.answer_citations`
- `conversation.answer_feedback`
- `conversation.retrieval_runs`
- `conversation.retrieval_candidates`
- 可选 `conversation.answer_events`，用于可靠 SSE 游标恢复。

关键约束：

- 同一会话最多一个 `PENDING/RETRIEVING/STREAMING` Answer；使用部分唯一索引；
- Message 和 Answer 不物理覆盖历史；
- Citation 保存回答时快照，不依赖未来当前版本；
- Feedback 对 `(answer_id, user_id)` 唯一并可幂等更新；
- RetrievalCandidate 对 `(retrieval_run_id, chunk_id)` 唯一；
- Answer 保存模型、Prompt、检索配置和索引 generation。

## 6. 真实 PARSE 阶段

### 6.1 标准产物

定义版本化 `ParsedDocument`：

```python
class ParsedElement(BaseModel):
    element_id: str
    type: Literal["heading", "paragraph", "list_item", "table", "sheet_region"]
    text: str | None
    table: dict | None
    heading_path: list[str]
    locator: dict

class ParsedDocument(BaseModel):
    schema_version: Literal["1.0"]
    title: str
    source_type: str
    elements: list[ParsedElement]
```

### 6.2 实现要求

- 从 raw object 读取真实飞书内容，不能只构造路径；
- Parser 接口与具体格式实现分离；
- V1 首先支持飞书 Docx/Wiki 已获取结构，随后支持 DOCX/PDF/XLSX；
- 表格保留表头、行列和定位；
- 不执行宏、脚本或外部资源；
- parsed object 先写临时 key，再原子发布固定 key；
- 记录 parser name/version、元素数、截断和错误；
- 相同输入重复执行覆盖同一版本产物，不追加。

## 7. Model Gateway

新增 `backend/app/model_gateway/`：

- `base.py`：`ChatRequest/ChatResponse/EmbeddingRequest/EmbeddingResponse/RerankRequest/RerankResponse`；
- `openai_compatible.py`：chat/embedding 实现；
- `factory.py`：按活动配置创建；
- `errors.py`：稳定错误分类；
- `schemas.py`：供应商响应严格校验。

要求：

- 配置来自数据库活动 revision，密钥只从 SecretValue 解密；
- Worker 不直接读取前端表单或拼供应商 URL；
- 明确 connect/read/total timeout；
- 只对网络、429、临时 5xx 有限重试；
- 400/401/403、Schema 错误不做无意义重试；
- 日志不得包含正文、Prompt、Token 或密钥；
- 记录 request_id、model、耗时、Token 用量和稳定错误码；
- 测试连接与业务调用共用协议适配器，避免两套行为。

## 8. Classification Service

### 8.1 输出契约

```python
class FieldEvidence(BaseModel):
    field: str
    locator_ids: list[str]
    excerpts: list[str] = []

class ClassificationOutput(BaseModel):
    relevance: Literal["RELEVANT", "IRRELEVANT", "UNCERTAIN"]
    relevance_confidence: float = Field(ge=0, le=1)
    product_code: str | None = None
    product_version_code: str | None = None
    document_type_code: str | None = None
    product_form_code: str | None = None
    is_domestic: bool | None = None
    module_name: str | None = None
    business_topic: str | None = None
    keywords: list[str] = []
    summary: str | None = None
    field_confidence: dict[str, float] = {}
    evidence: list[FieldEvidence] = []
    missing_fields: list[str] = []
    reason_summary: str
```

### 8.2 输入构造

按预算选择：标题、目录、一二级标题、摘要/前言/结论、章节首段、表格标题/表头/代表行、命中产品/版本术语附近上下文。每块包含稳定 locator，不发送整篇长文档。

输入哈希：

```text
SHA-256(content_sha256 + classification_config_revision + model_key
        + model_revision + prompt_revision + input_builder_revision)
```

### 8.3 Prompt 安全

- 系统消息明确正文是不可信数据；
- 正文放独立结构化边界，不拼入系统约束；
- 只允许 JSON 对象；
- code 必须来自本次 taxonomy；
- 未知返回 null，不猜测；
- evidence locator 必须来自输入；
- 不要求或保存隐藏思维链。

### 8.4 校验和决策

依次执行 JSON、Pydantic、置信度、code、产品版本归属、locator、长度/数量和 null 语义校验。首次失败允许一次带结构化错误的修复调用；仍失败进入任务重试，不用正则猜结果。

- `RELEVANT`：置信度 ≥ 0.80 且至少一处有效相关证据；
- `IRRELEVANT`：置信度 ≥ 0.90 且至少一处有效无关证据；
- 阈值不足、证据不足或矛盾：程序转 `UNCERTAIN`；
- `UNCERTAIN`：来源和版本进入待确认，不创建 Chunk；
- 字段缺失但相关性明确：正常入库，字段 null/other 并记录 missing_fields；
- 模型不可用时禁止默认相关。

### 8.5 事务边界

模型 HTTP 调用不得持有数据库事务或行锁：

1. 短事务读取版本、配置和已存在 input_hash；
2. 事务外构造输入并调用模型；
3. 短事务锁定版本，校验未下线/未被替代；
4. 插入 ClassificationResult；
5. 领域服务应用 Metadata 和状态；
6. 创建下一阶段任务。

## 9. 人工确认 API

新增管理员 API：

- `GET /api/v1/admin/classification-pending`
- `GET /api/v1/admin/classification-pending/{version_id}`
- `POST /api/v1/admin/classification-pending/{version_id}/confirm-relevant`
- `POST /api/v1/admin/classification-pending/{version_id}/confirm-irrelevant`
- `POST /api/v1/admin/classification-pending/{version_id}/reclassify`

确认相关：校验元数据，写字段来源 `MANUAL/MODEL`，从 CHUNK 创建新任务。确认无关：来源 OFFLINE。重新分类：必须选择活动配置 revision 或形成新 input hash。所有操作写审计日志，并使用 row_version 防止双人并发覆盖。

## 10. CHUNK 阶段

### 10.1 规则

- 优先按标题、段落、列表和表格边界；
- 默认目标 450～700 tokens，硬上限 900，最小 100；
- 普通文本相邻重叠 60～100 tokens；
- 表格优先完整保留，大表按行分段并重复表头；
- 标题路径、locator 和分类元数据写入每个 Chunk；
- 不把页眉页脚、空白和纯导航元素作为独立 Chunk；
- 参数必须配置化，并通过黄金问题评测调整，以上仅为初始值。

### 10.2 幂等

事务内删除/替换目标版本旧 Chunk 后批量写入；或先生成新 chunk generation 再切换。禁止重试后追加重复 ordinal。

## 11. EMBED 与 INDEX

### 11.1 Embedding

- 按 token/条数限制批处理；
- 校验返回数量、向量维度和有限数值；
- 任一批次最终失败则版本不进入 INDEX；
- 记录 model key/revision/dimension；
- 文档 Embedding 不允许 BM25-only 部分入库；
- 查询 Embedding 失败可降级 BM25-only。

### 11.2 检索引擎适配器

新增 `backend/app/search/`：

- `base.py`：bulk index、delete generation、BM25/vector search、health；
- `opensearch.py`：首选实现；
- `fake.py`：仅测试；
- `mapping.py`：版本化 mapping。

索引文档 ID：`chunk:{chunk_id}:generation:{generation}`。

索引字段至少包括正文、向量、source/version/chunk ID、标题、heading_path、locator、产品、版本、文档类型、产品形态、更新时间、来源优先级和 generation。

### 11.3 VERIFY 和 FINALIZE

在 FINALIZE 前新增 VERIFY：

- DB Chunk 数量等于索引成功数量；
- 抽样可按 ID 读取；
- generation 可按 source/version 过滤；
- metadata 与 version 一致；
- 校验失败不得将来源标记 QUERYABLE。

FINALIZE 在事务中锁定来源，确认未下线并原子切换 current_version。旧 generation 异步清理，清理失败不回滚已激活版本但必须告警。

## 12. Retrieval Service

### 12.1 QueryPlan

```python
class QueryPlan(BaseModel):
    operation: Literal["ANSWER", "SUMMARIZE", "RELATE", "EXPLAIN", "CLARIFY"]
    normalized_question: str
    query_texts: list[str]
    product_id: UUID | None = None
    version_ids: list[UUID] = []
    document_type_ids: list[UUID] = []
    required_fields: list[str] = []
    needs_clarification: bool = False
    clarification_question: str | None = None
```

所有 ID 必须来自数据库或会话已验证条件；禁止任意 URL、SQL、路径或工具名。显式页面筛选优先于模型推断；同维度新问题条件覆盖旧条件。

### 12.2 过滤

强制过滤：

- 来源 `status=QUERYABLE`；
- 只用 `current_version_id`；
- 当前 index generation；
- 用户显式产品/版本/文档类型；
- OFFLINE、PENDING_CONFIRMATION、FAILED 版本不得召回。

### 12.3 混合召回

初始参数：

- 每个 query_text BM25 top 50；
- 向量 top 50；
- 使用 RRF 融合，`k=60`；
- 去重后 top 40 送 Rerank；
- Rerank top 12 进入证据选择；
- 最终证据 4～8 个，受 token 预算、来源覆盖和重复度约束。

参数必须存于 retrieval 配置 revision，不硬编码为最终值。

### 12.4 Rerank 与证据

- Rerank 超时/5xx：使用 RRF 顺序并标记 `RERANK_FAILED`；
- Embedding 失败：BM25-only 并标记 `EMBEDDING_FAILED`；
- BM25 与向量均不可用：检索失败，不调用答案模型猜测；
- 同来源相邻重复 Chunk 合并或降权；
- 来源优先级只作为业务排序因素之一，不覆盖明显相关性；
- 同一事实冲突必须保留多个来源进入答案阶段；
- Evidence 包含 chunk、版本、标题、章节、原文 locator、更新时间和完整 score_details。

## 13. 问答、引用与 SSE

### 13.1 API

- `GET/POST /api/v1/conversations`
- `GET/PATCH/DELETE /api/v1/conversations/{id}`
- `GET/POST /api/v1/conversations/{id}/messages`
- `GET /api/v1/answers/{id}`
- `GET /api/v1/answers/{id}/events?after={event_id}`
- `POST /api/v1/answers/{id}/cancel`
- `PUT /api/v1/answers/{id}/feedback`
- `GET /api/v1/answers/{id}/citations/{citation_no}`

### 13.2 Answer 状态

`PENDING → RETRIEVING → STREAMING → SUCCEEDED`，以及 `FAILED/CANCELED`。更细阶段写 `progress_stage=UNDERSTANDING/RERANKING/GENERATING/VALIDATING`，不扩散为不稳定业务状态。

### 13.3 生成约束

- 只把最终 Evidence 作为企业事实上下文；
- 每个事实块必须携带 citation_nos；
- 资料不足返回 `NO_EVIDENCE/LOW_EVIDENCE`，不调用通用记忆补事实；
- 冲突输出必须说明不同值、来源和更新时间；
- 结构化规格优先输出表格；
- 输出先经过 Pydantic/JSON 校验，再校验引用编号和证据蕴含；
- 引用不到任何证据的关键结论删除或降级，不自动补一个引用编号。

### 13.4 SSE 可靠性

- API 从持久化状态或 answer_events 输出，不直接代理 Worker 内存流；
- 事件包含递增 event_id；
- 客户端携带 after/Last-Event-ID 可恢复；
- 重连不得创建第二个 Answer；
- 心跳事件不改变业务状态；
- 完成、失败、取消是终结事件；
- SSE 断开不取消后台任务，用户显式 cancel 才取消。

## 14. 前端替换

### 14.1 API 层

- 将 `frontend/src/api/conversations.ts` 拆为真实 API；
- 删除模块级可变 Mock 数组；
- 保留现有 TypeScript 契约，按后端响应修正；
- ConversationWorkspaceContext 使用真实 list/create/update；
- 新消息提交后进入 Answer 事件订阅；
- 切换会话取消旧页面订阅，但不取消后台答案；
- 网络错误保留用户输入和筛选。

### 14.2 页面状态

- 初始、检索中、重排中、生成中、完成、资料不足、冲突、降级、失败、取消；
- 引用可展开并定位原文；
- 降级提示不可宣称结果完全等价；
- 同一会话回答进行中时禁用重复提交并处理后端 409；
- 页面刷新从后端恢复会话、消息和 Answer 状态；
- 最近会话按后端 last_message_at 更新。

## 15. 配置

新增/扩展活动 revision：

- `classification`：taxonomy、阈值、输入预算、Prompt revision；
- `chunking`：目标/最大 token、overlap、表格策略；
- `retrieval`：BM25/vector topK、RRF k、rerank topK、证据数量/预算；
- `model` 或现有 `llm`：chat/classification/embedding/rerank 模型键和端点引用；
- `index`：引擎、index alias、mapping revision。

任务启动时保存 revision 快照；运行中配置变化不影响当前任务。配置发布不得自动重跑全部历史文档，重分类/重索引必须由管理员显式创建批量任务。

## 16. 错误、重试和恢复

| 环节 | 可重试 | 最终行为 |
|---|---|---|
| 模型/Embedding/Rerank 网络、429、临时 5xx | 是 | 指数退避，耗尽后失败或按规则降级 |
| 401/403/无效配置 | 否 | FAILED + 明确配置错误 |
| 分类 JSON 首次非法 | 模型内修复一次 | 仍非法进入任务重试 |
| Chunk 配置或 ParsedDocument 非法 | 否 | FAILED，修复后手动重试 |
| 文档 Embedding 数量/维度错误 | 有限 | 版本不可激活 |
| INDEX bulk 部分失败 | 是 | 只重试失败项，VERIFY 前不得激活 |
| Query Embedding 失败 | 降级 | BM25_ONLY + flag |
| Rerank 失败 | 降级 | RRF 顺序 + flag |
| 两种召回都失败 | 否 | Answer FAILED，不生成猜测答案 |
| Worker 租约过期 | 回收 | 旧 attempt ABANDONED，幂等重跑 |
| 新版处理失败 | 按阶段 | 旧 current_version 继续可查询 |

## 17. 可观察性和审计

记录但不包含正文/密钥：

- task/attempt/source/version/answer/retrieval_run ID；
- stage、排队/执行耗时、重试次数；
- model/config/prompt/index revision；
- 输入块数、Chunk 数、Embedding 数、索引成功数；
- BM25/vector/fusion/rerank/evidence 候选数量；
- 检索模式和 degradation flags；
- LLM/Embedding/Rerank 耗时和 Token 用量；
- 稳定错误 category/code；
- 人工确认、重分类、配置发布和批量重索引写审计日志。

核心指标：分类成功率、UNCERTAIN 比例、人工修改率、各文档类型分布、入库耗时、Chunk/索引不一致数、检索召回质量、无依据比例、Rerank/Embedding 降级率、首 token 和端到端延迟。

## 18. 测试与评测

### 18.1 单元测试

- 分类输入窗口、预算、去重和 locator；
- Schema、code、版本归属、null/false、阈值和 evidence 校验；
- Prompt 注入不能改变输出协议；
- Chunk 标题/段落/列表/表格边界及幂等；
- Embedding 数量、维度和异常值；
- RRF、去重、过滤、优先级、冲突和证据预算；
- Citation 编号和内容块校验；
- QueryPlan 白名单和显式筛选优先级。

### 18.2 集成测试

- Fake Model/Search Adapter 覆盖成功、非法 JSON、修复、超时、429、5xx；
- 相同分类 input_hash 并发只产生一个有效结果；
- UNCERTAIN 不创建 Chunk，确认后从 CHUNK 继续；
- 重跑阶段不产生重复 Chunk/索引；
- INDEX 部分失败后恢复，VERIFY 才允许 FINALIZE；
- 新版失败时旧版仍可检索；
- BM25-only 和 Rerank 降级；
- SSE 断线重连、after cursor、完成/失败/取消；
- 同一会话并发提交返回 409；
- 来源下线后历史 Citation 快照仍可读取。

### 18.3 黄金样本

分类集：人工标注 30～50 份起步，覆盖三种相关性、12 类文档、不同来源格式、标题误导、短文、长文、表格、注入和敏感字段。

RAG 集：沿用 `docs/RAG业务黄金问题集_V0.1.*`，每题补充：

- 期望关键答案点；
- 允许/禁止来源；
- 期望产品/版本/文档类型过滤；
- 期望 evidence chunk；
- 充分、部分、冲突或无依据标签。

指标：分类 Precision/Recall/F1、类型字段准确率、Recall@K、MRR/nDCG、证据 Precision、Citation 正确率、关键答案点覆盖率、无依据正确拒答率。

## 19. 安全

- 文档正文和用户问题均为不可信输入；
- 不允许正文覆盖系统 Prompt、taxonomy 或工具白名单；
- 不记录完整 Prompt/正文、OAuth token、API key；
- 引用 excerpt 限长并按权限返回；
- 只允许已注册的检索能力，不执行模型输出的 URL/SQL/文件路径；
- 外部模型数据范围和脱敏策略必须在生产启用前确认；
- CSV/Excel 导出继续防公式注入；
- 管理命令使用管理员权限、row_version 和审计。

## 20. 分阶段实施计划

### Phase 0：基线保护

- 记录 `git status`、迁移 head、后端/前端测试结果；
- 不覆盖当前前端未提交修改；
- 为新模块建立 feature flags：真实分类、真实索引、真实 QA 默认关闭。

出口：现有测试基线可复现。

### Phase 1：目录统一

- 文档类型增量迁移；
- QueryComposer 改真实 catalog；
- API 目录测试和前端构建。

出口：前后端只存在一套文档类型 code。

### Phase 2：数据模型和真实 Parse

- classification_results、metadata、chunks；
- ParsedDocument 和真实飞书 parser；
- 幂等/错误测试。

出口：真实 ParsedDocument 可定位并可重复生成。

### Phase 3：Model Gateway 和分类器

- 统一 Gateway；
- 分类输入、Prompt、Schema、校验、缓存；
- 人工确认 API；
- 分类黄金集。

出口：Mock 分类关闭后，相关/无关/不确定和 12 类元数据真实可追踪。

### Phase 4：Chunk/Embedding/Index

- Chunk；
- Embedding；
- OpenSearch Adapter；
- VERIFY/FINALIZE；
- generation 清理。

出口：只有真实索引校验通过的版本进入 QUERYABLE。

### Phase 5：Retrieval

- QueryPlan；
- BM25/vector/RRF/Rerank/evidence；
- retrieval_runs/candidates；
- 黄金问题检索评测。

出口：独立 Retrieval Service 能返回可解释证据，不生成答案。

### Phase 6：Conversation/QA/SSE

- 会话、消息、答案、引用、反馈；
- Answer Worker；
- SSE 持久化恢复；
- 前端替换 Mock。

出口：刷新、断线、多轮、引用、失败和取消行为可验证。

### Phase 7：质量门与上线

- 分类/RAG 基准；
- 性能、故障、安全和数据恢复测试；
- 先影子运行，比较 Mock/旧流程与真实结果；
- 分环境启用 feature flag；
- 监控降级率和无依据率。

出口：满足第 21 节验收标准后启用生产流量。

## 21. 验收标准

| 编号 | 验收要求 |
|---|---|
| AC-CLS-001 | 前后端和数据库使用同一套 12 类稳定 code |
| AC-CLS-002 | 分类器基于 ParsedDocument 内容而非 token/文件名默认判定 |
| AC-CLS-003 | 分类输出经过 Schema、taxonomy、版本归属和 evidence 校验 |
| AC-CLS-004 | UNCERTAIN 不创建 Chunk，人工确认后从 CHUNK 继续 |
| AC-CLS-005 | 分类运行、模型、Prompt、配置和输入哈希可追溯 |
| AC-ING-001 | Chunk 可回溯原文位置且重复执行不重复 |
| AC-ING-002 | Embedding 数量/维度和索引数量校验通过才可激活 |
| AC-ING-003 | 新版失败不影响旧版继续查询 |
| AC-RAG-001 | 只召回 QUERYABLE 的 current_version/current generation |
| AC-RAG-002 | 页面产品、版本、文档类型条件真实进入检索过滤 |
| AC-RAG-003 | Embedding/Rerank 降级有明确 flag，双召回失败不生成猜测答案 |
| AC-RAG-004 | 每个关键企业事实有有效 Citation，历史引用保存快照 |
| AC-QA-001 | 会话和消息刷新后可恢复，浏览器不再使用内存 Mock |
| AC-QA-002 | SSE 断线可按事件游标恢复且不重复创建 Answer |
| AC-QA-003 | 同会话并发回答受约束，取消和失败是可恢复终态 |
| AC-TEST-001 | 分类黄金集与 RAG 黄金集产生可保存、可比较的报告 |
| AC-TEST-002 | 后端测试、前端构建、迁移 upgrade/downgrade 检查通过 |
| AC-SEC-001 | 正文提示注入不能改变分类、查询计划或工具边界 |
| AC-OPS-001 | 关键阶段、模型、检索、降级和失败有指标与结构化日志 |

## 22. 明确非目标

- 不实现开放式工具调用或多 Agent 自主协作；
- 不接入公网 Web Search；
- 不让模型自动创建 taxonomy；
- 不把审计日志纳入 RAG；
- 不在 V1 自动 OCR 扫描 PDF；
- 不在同一 PR 完成全部阶段；
- 不以提高代码覆盖率代替真实分类/RAG 质量评测。

## 23. 交付和 PR 拆分建议

1. `catalog: unify document type taxonomy`
2. `ingestion: add classification metadata and chunk schema`
3. `ingestion: implement parsed document contract`
4. `model: add gateway and classification service`
5. `classification: add pending confirmation workflow`
6. `ingestion: implement chunking and embedding`
7. `search: add index adapter verify and generation activation`
8. `retrieval: implement hybrid retrieval and rerank`
9. `conversation: add persistence and APIs`
10. `qa: add answer worker citations and SSE`
11. `frontend: replace conversation and catalog mocks`
12. `evaluation: add classification and RAG quality gates`

每个 PR 必须包含迁移/兼容说明、测试证据、feature flag 和未验证风险。禁止把 schema、真实模型、检索、QA 和前端切换塞入一个不可回滚 PR。

## 24. 可直接交给实现 Agent 的提示词

```text
你正在维护项目：D:\Projects\ae-knowledge-platform

总任务：按 docs/详细设计/19_分类与RAG完整实施设计_V0.1.md 分阶段实现真实文档分类和 RAG。不要一次完成全部阶段，只执行用户明确指定的 Phase/PR。

开始前必须阅读：
1. docs/详细设计/19_分类与RAG完整实施设计_V0.1.md
2. docs/详细设计/04_文档接入与治理流水线_V0.1.md
3. docs/详细设计/05_LLM文档分类器_V0.1.md
4. docs/详细设计/06_异步任务与调度_V0.1.md
5. docs/详细设计/07_RAG检索与问答生成_V0.1.md
6. docs/详细设计/08_后端API与SSE接口_V0.1.md
7. backend/app/worker/pipeline.py
8. backend/app/worker/runner.py
9. backend/app/db/models/knowledge.py
10. frontend/src/api/conversations.ts

工作规则：
- 先运行 git status --short，保护所有用户未提交修改。
- 使用 rg 查证入口、模型、迁移 head、API 和测试，不猜测。
- 手工编辑使用 apply_patch。
- 先写行为测试，再实现最小代码。
- 外部 HTTP 调用不能持有数据库事务或行锁。
- 正文、Prompt、Token、API Key 不进入日志。
- 所有派生产物必须幂等；重复任务不能追加重复 Chunk、索引或 Answer。
- 只有真实 Chunk/Embedding/索引 VERIFY 通过的版本才能 QUERYABLE。
- 模型不可用时禁止默认相关或生成无依据产品事实。
- 每完成一个 Phase，运行最窄测试和必要的全量测试，报告命令与结果。
- 不得修改无关前端布局、认证、审计或日志代码。

每阶段交付格式：
Changes：文件和行为
Migrations：upgrade/downgrade/兼容性
Tests：精确命令
Results：通过/失败数量
Acceptance Criteria：逐项 PASS/FAIL/UNVERIFIED
Unverified：未验证项
Remaining Risks：剩余风险和 feature flag 状态
```

## 25. 推荐从哪里开始

首个实现 Agent 只执行 Phase 0 和 Phase 1：

1. 确认 Alembic 当前唯一 head；
2. 新增 12 类文档类型的增量迁移；
3. 增加目录 API 测试，校验 code、顺序、启用状态；
4. 将 QueryComposer 改为真实 catalog API；
5. 删除该组件对 `CATALOG_OPTIONS` 的依赖；
6. 验证筛选失败不影响提问；
7. 运行迁移检查、`pytest backend/tests/test_config_api.py` 和 `npm run build`；
8. 停止，不提前实现分类器。

Phase 1 合并后，再由独立 Agent 执行 Phase 2。这样可以先冻结 taxonomy，避免真实分类结果产生后再次迁移稳定 code。
