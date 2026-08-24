# AE 内部知识平台 V1——后端 API 与 SSE 接口详细设计

版本：V0.1
状态：详细设计草稿
文档编号：DD-08
依赖：DD-02《领域模型与状态机》、DD-03《数据库详细设计》、DD-04《文档接入与治理流水线》、DD-06《异步任务与调度》、DD-07《RAG 检索与问答生成》

## 1. 设计目标

为 React 前端和后台 Worker 提供稳定、可版本化、可测试的 FastAPI 契约，使用户能够登录、绑定飞书、提交文档、查询处理状态、进行知识问答和管理系统，同时保证：

- API Router 不直接修改领域状态或访问 Repository；
- 耗时工作通过数据库任务执行，不占用普通 HTTP 请求；
- 重复请求、并发修改、断线重连和进程重启有确定行为；
- 错误响应可被前端稳定识别，不依赖中文错误文本；
- SSE 只传输已持久化或可重建的状态，不依赖单实例内存；
- OpenAPI Schema、Pydantic Schema 和测试契约一致。

## 2. API 范围

V1 API 分为：

1. 认证与当前用户；
2. 飞书绑定和文档发现；
3. 知识来源提交、状态和治理；
4. 会话、提问、SSE、引用和反馈；
5. 分享与导出；
6. 任务和系统管理；
7. 分类、产品、版本、文档类型和模型配置；
8. 健康检查和运行统计。

不提供：诊断报告、CDT 日志分析、文档可见性权限配置和操作审计 API。

## 3. 基础约定

### 3.1 路径与版本

- 业务 API 前缀：`/api/v1`；
- 资源使用复数名词和 kebab-case；
- JSON 字段使用 snake_case；
- 主键使用 UUID 字符串；
- 时间使用带时区的 RFC 3339 UTC 字符串；
- 金额以外的精确数值、版本号、型号不得在 JSON 中自动转换格式；
- 新增可选字段属于兼容变更，删除/改义字段必须进入新 API 版本。

### 3.2 成功响应

单资源：

```json
{
  "data": {},
  "meta": {
    "request_id": "01J..."
  }
}
```

列表资源：

```json
{
  "data": [],
  "meta": {
    "request_id": "01J...",
    "next_cursor": "opaque-token",
    "has_more": true
  }
}
```

`204 No Content` 不返回 envelope。文件下载和 SSE 使用各自媒体类型。

### 3.3 错误响应

错误采用 `application/problem+json`：

```json
{
  "type": "https://ae-kb.example/problems/source-not-owner",
  "title": "无法撤回该文档",
  "status": 403,
  "code": "SOURCE_NOT_OWNER",
  "detail": "只有提交者可以撤回该知识来源",
  "instance": "/api/v1/knowledge-sources/...",
  "request_id": "01J...",
  "errors": []
}
```

`code` 是前端判断依据，`detail` 用于展示并允许调整措辞。字段错误放入 `errors`：

```json
{
  "field": "filters.product_version_id",
  "code": "VERSION_NOT_IN_PRODUCT",
  "message": "所选版本不属于该产品"
}
```

### 3.4 HTTP 状态码

| 状态码 | 使用场景 |
|---:|---|
| 200 | 查询或幂等命令返回已有结果 |
| 201 | 创建新资源 |
| 202 | 已创建异步任务 |
| 204 | 删除、撤销等无响应体成功 |
| 400 | 请求语义错误或无法解析 |
| 401 | 未登录或会话失效 |
| 403 | 不满足最小所有权/管理员操作规则 |
| 404 | 资源不存在，或对当前用户不可定位 |
| 409 | 状态冲突、重复资源、存在未完成回答 |
| 412 | `If-Match` 版本不一致 |
| 413 | 上传文件或请求体过大 |
| 415 | 文件媒体类型不支持 |
| 422 | Pydantic 字段校验失败 |
| 429 | 用户或接口限流 |
| 502/503/504 | 外部依赖错误、服务不可用或超时 |

### 3.5 请求追踪

客户端可传 `X-Request-ID`，格式无效时服务端重建；响应始终返回最终 `X-Request-ID`。内部调用传递 `trace_id`。不得把 Token、密码、文档正文或完整问题写入访问日志。

## 4. 认证、会话和 CSRF

### 4.1 登录会话

登录成功后设置随机会话 Cookie：

- `HttpOnly`；
- `Secure`（HTTPS 环境）；
- `SameSite=Lax`；
- 限定 Path 和有效期；
- Cookie 只保存随机令牌，数据库只保存其哈希。

所有非 GET/HEAD/OPTIONS Cookie 认证请求必须携带 CSRF Token。具体密码哈希、会话轮换和安全头在 DD-12 定义。

### 4.2 认证接口

| 编号 | 方法与路径 | 说明 |
|---|---|---|
| API-AUTH-001 | `POST /api/v1/auth/password/login` | 账号密码登录 |
| API-AUTH-002 | `POST /api/v1/auth/logout` | 注销当前会话，幂等 |
| API-AUTH-003 | `GET /api/v1/auth/me` | 当前用户、飞书绑定状态和 CSRF 信息 |
| API-AUTH-004 | `POST /api/v1/auth/feishu/start` | 创建 state 并返回飞书授权地址 |
| API-AUTH-005 | `GET /api/v1/auth/feishu/callback` | 校验 state/code，登录或绑定 |
| API-AUTH-006 | `DELETE /api/v1/auth/feishu/binding` | 解除飞书绑定；存在其他登录方式时允许 |

密码登录请求：

```json
{
  "username": "eric",
  "password": "********"
}
```

错误统一返回 `INVALID_CREDENTIALS`，不暴露账号是否存在。

### 4.3 飞书身份匹配

飞书回调取得稳定 `user_id` 后，以 `(provider, tenant_key, provider_user_id)` 查询 `external_identities`：

1. 已绑定：登录对应系统用户；
2. 未绑定且当前已有登录会话：绑定到当前用户；
3. 未绑定且未登录：创建系统用户并绑定；
4. 同一飞书身份已被其他用户绑定：返回 `EXTERNAL_IDENTITY_ALREADY_BOUND`，不得重复创建。

`open_id` 可以作为飞书 API 调用字段保存，但不作为系统用户唯一业务键。首次扫码不会无条件新建账户，必须先执行上述匹配。

## 5. 分页、筛选和排序

### 5.1 Cursor 分页

列表默认使用 cursor 分页：

```text
?limit=20&cursor=opaque-token
```

- 默认 20，最大 100；
- cursor 是服务端签名或不可读编码，包含稳定排序键；
- cursor 与筛选条件绑定，改变筛选后旧 cursor 返回 `INVALID_CURSOR`；
- 返回 `next_cursor` 和 `has_more`，不承诺昂贵的总数；
- 管理统计需要总数时使用独立聚合接口。

### 5.2 排序

每个列表只开放白名单字段。默认：

- 会话：`last_message_at DESC, id DESC`；
- 知识来源：`updated_at DESC, id DESC`；
- 任务：`created_at DESC, id DESC`；
- 飞书发现：由飞书 API 游标和修改时间组织。

前端不能传任意数据库列名。

## 6. 幂等和并发控制

### 6.1 Idempotency-Key

创建类命令支持 `Idempotency-Key` 请求头：

- 提交飞书来源；
- 本地文件上传最终提交；
- 创建用户消息/回答；
- 手动重试任务；
- 创建分享和导出。

同一用户、接口和 Key：

- request hash 相同：返回首次响应；
- request hash 不同：返回 `409 IDEMPOTENCY_KEY_REUSED`；
- 首次仍处理中：返回同一资源或 `409 IDEMPOTENCY_IN_PROGRESS`；
- 默认记录保留 24 小时，最终值可配置。

业务唯一约束仍是最终防线。Idempotency-Key 不能替代飞书 token、文件 MD5、开放任务等数据库唯一约束。

### 6.2 乐观并发

可修改资源响应包含：

```http
ETag: "7"
```

修改请求传 `If-Match: "7"`。版本不一致返回 `412 RESOURCE_VERSION_MISMATCH` 和当前版本摘要。状态命令还必须经过领域状态机，不能只依赖 ETag。

### 6.3 批量命令

批量飞书提交和批量任务重试允许部分成功，使用 `207 Multi-Status` 或 200 业务结果数组。V1 统一采用 200/201 + item 结果：

```json
{
  "data": {
    "items": [
      {"client_item_id": "1", "status": "CREATED", "resource_id": "..."},
      {"client_item_id": "2", "status": "DUPLICATE", "existing_resource_id": "..."},
      {"client_item_id": "3", "status": "FAILED", "error_code": "..."}
    ]
  }
}
```

单项失败不得回滚其他已成功项。

## 7. 飞书绑定与文档发现 API

| 编号 | 方法与路径 | 说明 |
|---|---|---|
| API-FS-001 | `GET /api/v1/feishu/connection` | 查询绑定和授权可用状态 |
| API-FS-002 | `GET /api/v1/feishu/documents` | 分页发现当前用户可见云文档 |
| API-FS-003 | `POST /api/v1/feishu/documents/resolve` | 解析用户粘贴的 Docx/Wiki URL |
| API-FS-004 | `POST /api/v1/feishu/documents/submit` | 批量提交选中文档 |

发现接口筛选：

```text
?query=白皮书&resource_type=wiki,docx&modified_after=...&limit=50&cursor=...
```

响应项包含 token 的内部引用、标题、资源类型、最近修改时间、所有者摘要、是否已提交和已有 source_id。不得在前端暴露 user_access_token。

提交请求：

```json
{
  "items": [
    {"client_item_id": "row-1", "resource_token": "...", "resource_type": "wiki"},
    {"client_item_id": "row-2", "resource_token": "...", "resource_type": "docx"}
  ]
}
```

单次最大选择数量先设 50，属于可配置保护值。服务端逐项获取元数据并按 canonical token 去重。

## 8. 知识来源 API

### 8.1 接口目录

| 编号 | 方法与路径 | 说明 |
|---|---|---|
| API-KB-001 | `POST /api/v1/knowledge-sources/files` | 流式上传 Word/PDF/Excel |
| API-KB-002 | `GET /api/v1/knowledge-sources` | 查询来源列表 |
| API-KB-003 | `GET /api/v1/knowledge-sources/{source_id}` | 来源、当前版本、待处理版本和任务摘要 |
| API-KB-004 | `GET /api/v1/knowledge-sources/{source_id}/versions` | 版本历史 |
| API-KB-005 | `POST /api/v1/knowledge-sources/{source_id}/withdraw` | 提交者撤回/下线 |
| API-KB-006 | `POST /api/v1/knowledge-sources/{source_id}/restore` | 提交者恢复并重建查询状态 |
| API-KB-007 | `PATCH /api/v1/knowledge-sources/{source_id}/metadata` | 修改当前分类元数据 |
| API-KB-008 | `POST /api/v1/knowledge-sources/{source_id}/reclassify` | 创建重新分类任务 |
| API-KB-009 | `POST /api/v1/knowledge-sources/{source_id}/retry` | 重试失败处理 |
| API-KB-010 | `POST /api/v1/knowledge-sources/{source_id}/confirmation` | 处理待确认分类 |

### 8.2 本地文件上传

使用 `multipart/form-data`，字段 `file`。服务端流式处理，默认最大 100 MB，只支持配置允许的 Word、PDF 和 Excel MIME/扩展名组合。

成功创建：`201 Created`；响应：

```json
{
  "data": {
    "source_id": "...",
    "version_id": "...",
    "status": "PROCESSING",
    "task_id": "..."
  },
  "meta": {"request_id": "..."}
}
```

MD5 命中现有非下线来源时返回 `409 DUPLICATE_SOURCE`，problem 扩展字段包含 `existing_source_id`、标题和状态；不会把当前用户追加成共同所有者。

客户端断线不代表上传事务成功。客户端可使用同一 Idempotency-Key 查询或重试，服务端结合上传记录与 MD5 返回确定结果。

### 8.3 来源列表筛选

```text
?status=PROCESSING,FAILED
&source_type=FEISHU_WIKI,LOCAL_FILE
&submitted_by=me
&product_id=...
&document_type_id=...
&query=Analyzer
```

列表状态由 Source 主状态、`update_status`、当前 Version 阶段和最近 Task 错误组合形成，不允许前端自行推导复杂状态。

### 8.4 撤回与恢复

撤回请求可选原因：

```json
{"reason": "内容已过期"}
```

只有 `submitted_by_user_id` 对应提交者可以自行撤回；其他普通用户即使曾发现同一文档也不能撤回。管理员的系统维护能力作为最小管理规则保留，不扩展为文档可见性权限系统。

重复撤回返回 200 和当前 OFFLINE 状态。恢复时若 canonical key 已被另一个非下线来源占用，返回 `409 ACTIVE_SOURCE_ALREADY_EXISTS`。

### 8.5 待确认分类

```json
{
  "decision": "CONFIRM_RELEVANT",
  "metadata": {
    "product_id": "...",
    "product_version_id": null,
    "document_type_id": "...",
    "product_form": "国产化",
    "module_name": "Analyzer",
    "keywords": ["启动", "Kafka"]
  }
}
```

`decision`：`CONFIRM_RELEVANT`、`MARK_IRRELEVANT`。重新调用模型使用独立 reclassify API。确认相关后返回 202 和 CHUNK 任务；确认前不进入查询范围。

## 9. 查询条件与基础字典 API

| 编号 | 方法与路径 | 说明 |
|---|---|---|
| API-DICT-001 | `GET /api/v1/catalog/products` | 可用产品 |
| API-DICT-002 | `GET /api/v1/catalog/products/{product_id}/versions` | 产品版本 |
| API-DICT-003 | `GET /api/v1/catalog/document-types` | 文档类型 |
| API-DICT-004 | `GET /api/v1/catalog/product-forms` | 产品形态 |

字典返回稳定 code、显示名称和 ID。停用项不出现在新选择列表，但历史资源详情仍能解析其快照名称。

## 10. 会话 API

| 编号 | 方法与路径 | 说明 |
|---|---|---|
| API-CONV-001 | `POST /api/v1/conversations` | 新建会话 |
| API-CONV-002 | `GET /api/v1/conversations` | 当前用户会话列表 |
| API-CONV-003 | `GET /api/v1/conversations/{conversation_id}` | 会话基本信息 |
| API-CONV-004 | `GET /api/v1/conversations/{conversation_id}/messages` | 分页获取消息和回答 |
| API-CONV-005 | `PATCH /api/v1/conversations/{conversation_id}` | 修改标题或默认查询条件 |
| API-CONV-006 | `POST /api/v1/conversations/{conversation_id}/archive` | 归档 |
| API-CONV-007 | `POST /api/v1/conversations/{conversation_id}/restore` | 恢复归档/逻辑删除会话 |
| API-CONV-008 | `DELETE /api/v1/conversations/{conversation_id}` | 逻辑删除 |

创建请求：

```json
{
  "title": "T90000 规格咨询",
  "filters": {
    "product_id": null,
    "product_version_id": null,
    "document_type_id": null
  }
}
```

标题可省略，首个问题完成后由系统生成候选标题。系统生成标题失败不影响问答。

只有 ACTIVE 会话可提问；ARCHIVED 可以查看、恢复和导出/分享；DELETED 默认不出现在列表，可通过恢复入口定位。

## 11. 提问与回答 API

### 11.1 创建问题

| 编号 | 方法与路径 | 说明 |
|---|---|---|
| API-QA-001 | `POST /api/v1/conversations/{conversation_id}/messages` | 保存问题并创建回答任务 |
| API-QA-002 | `GET /api/v1/answers/{answer_id}` | 获取回答当前状态或最终内容 |
| API-QA-003 | `GET /api/v1/answers/{answer_id}/events` | SSE 订阅进度和最终回答 |
| API-QA-004 | `POST /api/v1/answers/{answer_id}/cancel` | 请求中止 |
| API-QA-005 | `POST /api/v1/answers/{answer_id}/retry` | 基于原问题创建新消息/回答 |
| API-QA-006 | `PUT /api/v1/answers/{answer_id}/feedback` | 新增或更新反馈 |
| API-QA-007 | `DELETE /api/v1/answers/{answer_id}/feedback` | 删除自己的反馈 |
| API-QA-008 | `GET /api/v1/answers/{answer_id}/citations/{citation_no}` | 引用详情和当前可访问状态 |

请求：

```json
{
  "content": "T90000 的内存呢？",
  "filters": {
    "product_id": null,
    "product_version_id": null,
    "document_type_id": null
  }
}
```

规则：

- `content` 去除首尾空白后 1～4,000 字符；
- filters 省略表示使用会话当前条件；filters 一旦出现就是完整替换，三个可空字段都必须出现，显式 null 表示清空，避免部分合并产生隐含条件；
- 事务创建 UserMessage、PENDING Answer 和高优先级 `GENERATE_ANSWER` 任务；
- 同一会话存在未终结回答时返回 `409 ANSWER_ALREADY_IN_PROGRESS`；
- 成功返回 `202 Accepted`。

响应：

```json
{
  "data": {
    "message_id": "...",
    "answer_id": "...",
    "status": "PENDING",
    "events_url": "/api/v1/answers/.../events"
  },
  "meta": {"request_id": "..."}
}
```

### 11.2 回答表示

```json
{
  "id": "...",
  "status": "SUCCEEDED",
  "answer_type": "ANSWER",
  "summary": "T90000 配置 256GB 内存。",
  "blocks": [
    {
      "block_id": "b1",
      "type": "table",
      "content": {
        "columns": ["型号", "内存"],
        "rows": [["T90000", "256GB"]]
      },
      "citation_nos": [1]
    }
  ],
  "citations": [
    {
      "citation_no": 1,
      "document_title": "AE 硬件规格",
      "heading_path": ["当前型号"],
      "source_updated_at": "2026-08-12T02:00:00Z",
      "original_url": "https://...",
      "availability": "AVAILABLE"
    }
  ],
  "degradation_flags": [],
  "created_at": "...",
  "completed_at": "..."
}
```

回答 `content` 在数据库中保存规范结构及可渲染文本；API 返回结构化 blocks，前端不解析模型自由 Markdown 来猜表格和引用。

### 11.3 重试

用户重试不会覆盖旧失败/取消回答，而是在同一会话创建新的 UserMessage 和 Answer，并用 `retry_of_answer_id` 或业务关联记录来源。若知识或配置已更新，新回答使用当前激活配置；页面提示这是新的运行结果。

## 12. SSE 契约

### 12.1 响应头

```http
Content-Type: text/event-stream
Cache-Control: no-cache, no-transform
Connection: keep-alive
X-Accel-Buffering: no
```

反向代理必须关闭该路径缓冲。SSE 使用登录 Cookie，浏览器同源访问；不把会话 Token 放入 URL。

### 12.2 事件格式

```text
id: status:2
event: answer.status
data: {"answer_id":"...","status":"RETRIEVING","stage":"reranking"}

```

事件类型：

| event | 内容 |
|---|---|
| `answer.snapshot` | 连接建立时的当前完整状态 |
| `answer.status` | `PENDING`、查询理解、检索、Rerank、生成和校验等进度 |
| `answer.block` | 已验证回答 block，带稳定 block_id |
| `answer.citation` | 引用卡片 |
| `answer.warning` | 降级、部分依据或冲突提示 |
| `answer.done` | 最终状态、完成时间和 answer ETag |
| `answer.error` | 稳定 error_code、可展示信息和是否可重试 |
| `heartbeat` | 保活事件，不包含业务数据 |

### 12.3 持久化和重连

SSE Endpoint 不执行 RAG。`GENERATE_ANSWER` Worker 更新 Answer、RetrievalRun 和最终内容；SSE Endpoint 读取数据库并发送状态。

- 客户端传 `Last-Event-ID`；
- 状态和最终 block 使用确定性 event ID，可从 Answer 重建；
- 短暂的重复事件允许，客户端按 event ID 去重；
- 最终 Answer 已完成时，新连接立即发送 snapshot、全部 blocks/citations 和 done；
- API 实例重启后可在其他实例继续订阅；
- 心跳初始建议 15 秒，连接最长时间由代理配置确定；
- Worker 暂无状态变化时不制造虚假进度。

V1 不单独持久化每个 SSE 传输事件。业务状态与最终结果可重建；瞬时进度事件断线后不保证逐条补发。

### 12.4 慢客户端

每个连接使用有界发送缓冲。客户端长时间无法消费时关闭连接，业务任务继续运行；客户端随后通过 GET Answer 或重新连接 SSE 获取结果。不得让慢客户端阻塞 Worker 或数据库事务。

## 13. 反馈 API

`PUT /answers/{id}/feedback` 请求：

```json
{
  "rating": "NOT_HELPFUL",
  "reason_codes": ["MISSING_KEY_POINT", "WRONG_SOURCE"],
  "comment": "没有说明适用版本"
}
```

规则：

- `HELPFUL` / `NOT_HELPFUL`；
- 无帮助原因和评论均选填；
- 原因 code 来自配置化白名单；
- 同一用户对同一回答再次提交执行更新，返回 200；
- 仅 SUCCEEDED 的回答允许反馈；
- 评论长度默认最多 1,000 字符；
- 反馈进入运营统计，经业务确认后可形成黄金问题候选，不自动修改检索配置。

## 14. 引用与原文跳转

引用详情返回快照和实时可用状态：

```json
{
  "data": {
    "citation_no": 1,
    "supported_claim": "T90000 配置 256GB 内存",
    "document_title": "AE 硬件规格",
    "document_type": "产品规格",
    "heading_path": ["当前型号"],
    "locator": {"sheet": "硬件规格", "row": 12},
    "excerpt": "...",
    "original_url": "https://...",
    "availability": "AVAILABLE"
  }
}
```

`availability`：`AVAILABLE`、`SOURCE_OFFLINE`、`SOURCE_DELETED`、`EXTERNAL_UNAVAILABLE`。历史引用不自动替换为新版本。excerpt 来自回答时证据短快照或当前 chunk，受长度限制，不返回完整文档。

## 15. 分享与导出 API

| 编号 | 方法与路径 | 说明 |
|---|---|---|
| API-SHARE-001 | `POST /api/v1/conversations/{id}/shares` | 创建不可变内部分享快照 |
| API-SHARE-002 | `GET /api/v1/shares/{share_token}` | 查看分享快照，仍需登录 |
| API-SHARE-003 | `DELETE /api/v1/shares/{share_id}` | 撤销分享 |
| API-EXP-001 | `POST /api/v1/conversations/{id}/exports` | 创建导出任务 |
| API-EXP-002 | `GET /api/v1/exports/{export_id}` | 查询导出状态 |
| API-EXP-003 | `GET /api/v1/exports/{export_id}/download` | 下载就绪文件 |

分享只复制创建时的问题、成功回答和来源摘要，不复制来源全文。会话后续变化不影响快照。

导出返回 202，Worker 生成 Markdown 文件；普通文件使用短时下载 URL 或受认证下载流。飞书云文档导出不纳入 V1。

## 16. 任务管理 API

| 编号 | 方法与路径 | 说明 |
|---|---|---|
| API-TASK-001 | `GET /api/v1/admin/tasks` | 任务筛选和分页 |
| API-TASK-002 | `GET /api/v1/admin/tasks/{task_id}` | Task 和 Attempt 历史 |
| API-TASK-003 | `POST /api/v1/admin/tasks/{task_id}/retry` | 创建人工重试任务 |
| API-TASK-004 | `POST /api/v1/admin/tasks/retry-batch` | 批量重试 |
| API-TASK-005 | `POST /api/v1/admin/tasks/{task_id}/cancel` | 取消未开始或请求协作取消 |

筛选：状态、task_type、错误类别、source_id、version_id、时间范围。错误详情不得返回敏感正文或凭据。

人工重试必须重新校验业务对象和原任务错误类型。FAILED 原记录不改回 PENDING，新任务通过 parent_task_id 关联。

## 17. 配置与系统管理 API

### 17.1 配置接口

| 编号 | 方法与路径 | 说明 |
|---|---|---|
| API-CFG-001 | `GET /api/v1/admin/configs/{namespace}` | 查询版本列表和 ACTIVE |
| API-CFG-002 | `POST /api/v1/admin/configs/{namespace}/drafts` | 基于当前或指定版本创建草稿 |
| API-CFG-003 | `PATCH /api/v1/admin/configs/{namespace}/drafts/{revision}` | 修改草稿 |
| API-CFG-004 | `POST /api/v1/admin/configs/{namespace}/drafts/{revision}/validate` | 校验引用和 Schema |
| API-CFG-005 | `POST /api/v1/admin/configs/{namespace}/drafts/{revision}/activate` | 激活草稿 |
| API-CFG-006 | `GET /api/v1/admin/source-priorities` | 查询来源优先级 |

配置只接受定义好的 Pydantic discriminated union，不接受任意 JSON 直接写数据库。激活使用事务保证同 namespace 只有一个 ACTIVE。

### 17.2 系统状态与统计

| 编号 | 方法与路径 | 说明 |
|---|---|---|
| API-ADM-001 | `GET /api/v1/admin/dashboard/summary` | 查询、反馈、文档和任务摘要 |
| API-ADM-002 | `GET /api/v1/admin/statistics/queries` | 查询量、有/部分/无依据趋势 |
| API-ADM-003 | `GET /api/v1/admin/statistics/feedback` | 帮助率和低满意度问题 |
| API-ADM-004 | `GET /api/v1/admin/statistics/documents` | 处理、同步和失败趋势 |
| API-ADM-005 | `GET /api/v1/admin/system/dependencies` | 外部依赖健康摘要，不暴露密钥 |

统计用于运营和运行管理，不提供操作审计查询。

## 18. 用户管理 API

| 编号 | 方法与路径 | 说明 |
|---|---|---|
| API-USER-001 | `GET /api/v1/admin/users` | 用户列表 |
| API-USER-002 | `POST /api/v1/admin/users` | 创建账号密码用户 |
| API-USER-003 | `GET /api/v1/admin/users/{user_id}` | 用户状态和登录方式摘要 |
| API-USER-004 | `PATCH /api/v1/admin/users/{user_id}` | 修改显示信息 |
| API-USER-005 | `POST /api/v1/admin/users/{user_id}/disable` | 停用登录 |
| API-USER-006 | `POST /api/v1/admin/users/{user_id}/enable` | 恢复登录 |
| API-USER-007 | `POST /api/v1/admin/users/{user_id}/password-reset` | 管理员发起密码重置 |

停用用户只禁止后续登录和创建业务操作；其已入库知识默认继续参与查询。该规则需在产品评审最终确认。

V1 不建设复杂角色/文档权限模型，但系统仍需区分普通入口与系统管理入口；该最小管理员标识只控制平台维护命令。

## 19. 健康检查

| 路径 | 用途 | 行为 |
|---|---|---|
| `GET /health/live` | 进程存活 | 不访问外部依赖 |
| `GET /health/ready` | 接流量准备 | 检查数据库和关键本地配置；搜索/模型状态按部署策略 |
| `GET /metrics` | 指标抓取 | 仅对监控网络开放，不走业务前端 |

健康接口不得返回连接串、Token、模型密钥或内部堆栈。

## 20. 限流和请求保护

初始保护策略按部署实测调整：

- 登录按账号标识和来源网络双维度限流；
- 提问按用户限制并发回答为 1，可配置单位时间请求量；
- 上传按用户限制并发和每日总量；
- 飞书发现限制翻页频率，避免消耗用户授权配额；
- 管理批量任务限制单次条目数；
- SSE 限制每用户和每 Answer 的连接数；
- 反向代理与 FastAPI 同时限制 body 大小和慢速上传。

429 响应包含 `Retry-After`，但不暴露其他用户负载。

## 21. FastAPI 分层实现

示例调用链：

```text
APIRouter
  → Depends(CurrentUser, UnitOfWork, IdempotencyContext)
  → Application Service / Command Handler
  → Domain Aggregate / Domain Service
  → Repository Interface
  → SQLAlchemy Repository
  → PostgreSQL
```

目录建议：

```text
src/ae_knowledge/
├── api/
│   ├── dependencies.py
│   ├── errors.py
│   ├── pagination.py
│   └── v1/
│       ├── auth.py
│       ├── feishu.py
│       ├── knowledge_sources.py
│       ├── conversations.py
│       ├── answers.py
│       ├── admin_tasks.py
│       └── admin_configs.py
├── conversation/application/
├── knowledge/application/
├── task/application/
└── shared/infrastructure/
```

规则：

- Router 只做协议解析、依赖注入和响应映射；
- Pydantic API Schema 不作为 SQLAlchemy ORM Model；
- 领域异常集中映射 Problem Details；
- 外部飞书、模型和搜索响应先转内部模型；
- API 事务由 Application Service 定义，不能由 Router 零散 commit；
- 阻塞文件处理不进入 API 事件循环。

## 22. OpenAPI 和兼容性

- FastAPI 生成 `/openapi.json`，CI 保存并检查破坏性差异；
- 每个 API 有 `operation_id`、标签、稳定错误 code 和请求/响应示例；
- 管理和普通接口在文档中分组；
- SSE 使用单独 AsyncAPI 风格事件说明，因为 OpenAPI 对事件流表达有限；
- 前端类型从已审查的 OpenAPI 生成或由共享 Schema 工具生成，禁止手工维护两套不一致枚举；
- 数据库新增状态 code 前，必须先让旧前端能容忍未知展示值。

## 23. 测试设计

### 23.1 Schema 与单元测试

- 请求边界、枚举和跨字段校验；
- 领域异常到 HTTP/Problem code 映射；
- cursor 编解码、筛选绑定和过期处理；
- Idempotency-Key 相同/不同 request hash；
- ETag/If-Match；
- SSE event ID、序列化和客户端去重契约。

### 23.2 API 集成测试

- 密码和飞书首次/重复登录匹配；
- 两用户并发提交同一飞书 token 或 MD5；
- B 用户不能撤回 A 提交的来源；
- 流式上传过大、类型不符、连接中断和数据库提交失败；
- 批量飞书提交部分成功；
- 同一会话并发提问只有一个成功创建；
- 创建问题、Answer 和 GENERATE_ANSWER 任务原子提交；
- SSE 断线、Last-Event-ID 重连、API 重启后恢复；
- Answer 完成与取消竞争；
- 回答与 citations 原子提交；
- 归档、删除、恢复、分享和导出状态约束；
- 手动重试不改写旧 FAILED 任务；
- 配置激活并发时只有一个 ACTIVE。

### 23.3 契约与 E2E

- OpenAPI breaking-change 检查；
- React 生成类型编译；
- 浏览器 Cookie、CSRF、SSE 和代理缓冲联调；
- 错误 code 映射为正确页面提示；
- 100 MB 边界上传和分页最大 limit；
- 30 用户目标规模的查询/SSE 基础压测。

## 24. 验收追踪

| 需求/设计规则 | API | 建议测试编号 |
|---|---|---|
| 账号密码和飞书扫码登录 | API-AUTH-001～006 | TC-API-AUTH-001～020 |
| 用户发现并批量选择飞书文档 | API-FS-001～004 | TC-API-FS-001～018 |
| 本地文件上传、去重和状态 | API-KB-001～004 | TC-API-KB-001～025 |
| 提交者撤回，其他用户不可撤回 | API-KB-005～006 | TC-API-KB-030～038 |
| 分类待确认不入库 | API-KB-007～010 | TC-API-KB-040～052 |
| 自然语言问答和多轮追问 | API-QA-001～005 | TC-API-QA-001～030 |
| SSE 断线可恢复 | API-QA-002～004 | TC-API-SSE-001～018 |
| 来源引用和失效提示 | API-QA-008 | TC-API-CITE-001～012 |
| 反馈原因选填 | API-QA-006～007 | TC-API-FB-001～010 |
| 失败任务可查看和重试 | API-TASK-001～005 | TC-API-TASK-001～020 |

## 25. 待确认项

1. 飞书 OAuth/扫码在公司应用中的实际回调域名和租户标识字段；
2. 普通用户解除飞书绑定时，对已登记 Wiki 同步凭据的处理方式；
3. V1 是否正式提供会话恢复已删除状态的页面入口；
4. 分享撤销是否进入 V1；
5. 导出文件的临时下载链接有效期和失败/部分完成回答的导出范围；
6. 管理员最小标识的初始化和维护方式；
7. BM25 不可用时 API 采用 503 还是允许 vector-only 的最终规则；
8. 生产反向代理的 SSE 连接最长时间和心跳要求。

## 26. 与后续设计的接口

- DD-09 使用本接口设计完成普通用户端页面原型和异常态；
- DD-10 完成会话、分享和导出业务细节；
- DD-11 完成管理后台页面、统计口径和配置操作；
- DD-12 完成认证、Cookie、CSRF、外部服务和上传安全；
- DD-13 将 API、SSE 和并发场景映射为自动化测试与验收。
