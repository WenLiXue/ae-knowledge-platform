# AE 内部知识平台 V1——LLM 模型管理与服务配置详细设计

版本：V0.1  
状态：已确认方案，待实现  
文档编号：DD-20  
日期：2026-08-25  
依赖：DD-03、DD-05、DD-07、DD-08、DD-11、DD-12、DD-14、DD-17

## 1. 设计目标

为管理员提供一个简单、边界清晰的 LLM 配置入口，使其能够：

1. 在“模型管理”中维护系统可连接的模型；
2. 在“服务配置”中指定各业务服务使用哪个模型；
3. 复用同一个模型配置，不重复填写 Endpoint 和凭据；
4. 只展示管理员完成配置所需的字段，由系统维护超时、重试等技术默认值；
5. 保持模型密钥不回显、配置可版本化、变更可审计。

面向管理员的核心心智模型只有两个问题：

- 系统中有哪些可用模型？
- 每项 AI 服务使用哪个模型？

## 2. 已确认决策

| 编号 | 决策 |
|---|---|
| MC-01 | 左侧导航保留“LLM 配置”，不增加新的一级或二级菜单 |
| MC-02 | 页面内部使用“模型管理”“服务配置”两个 Tab |
| MC-03 | 模型连接信息与业务服务绑定分开维护 |
| MC-04 | V1 不强制配置主模型和备用模型，也不在基础页面展示故障切换策略 |
| MC-05 | V1 不向管理员展示温度、Top P、最大 Token、超时、重试次数等技术参数 |
| MC-06 | 同一个 CHAT 模型可以同时用于智能问答和文档分类 |
| MC-07 | 服务只能选择已启用且能力类型匹配的模型 |
| MC-08 | Embedding 模型变更必须提示需要重建向量索引，不静默切换现有索引 |
| MC-09 | API Key 按模型配置独立加密保存，读取接口只返回是否已配置 |
| MC-10 | V1 不提供模型删除；模型通过启用、停用管理生命周期 |

## 3. 范围

### 3.1 V1 范围

- 模型配置列表；
- 新增和编辑模型配置；
- 模型连接测试；
- 启用和停用模型；
- 智能问答、文档分类、Embedding、Rerank 的模型绑定；
- 类型匹配和引用完整性校验；
- 配置版本、密钥脱敏和操作审计；
- 旧版单条 LLM 配置的数据迁移。

### 3.2 V1 不包含

- 强制主备模型；
- 负载均衡、权重路由和成本路由；
- 管理员自定义重试状态码、熔断和并发限制；
- 多租户模型额度和计费；
- 模型市场、自动发现和自动同步模型列表；
- 在页面配置 Prompt、temperature、top_p、max_tokens；
- 删除模型及密钥恢复。

备用模型属于未来可选的“高级设置”。只有出现明确稳定性需求时，才在服务绑定上增加可选的 fallback 引用，不改变模型管理的基础结构。

## 4. 概念与边界

### 4.1 模型配置

模型配置描述“如何连接一个具备明确能力的模型”，包含展示名称、能力类型、协议、Endpoint、上游模型名称和凭据。

模型配置不描述它被哪个业务使用。

### 4.2 服务绑定

服务绑定描述“某项业务使用哪个模型配置”。绑定只保存模型配置 ID，不重复保存模型名称、Endpoint 或密钥。

### 4.3 模型类型与服务类型

| 模型类型 | 含义 | 可绑定服务 |
|---|---|---|
| `CHAT` | 文本生成或结构化生成模型 | `QA`、`DOCUMENT_CLASSIFICATION` |
| `EMBEDDING` | 文本向量模型 | `DOCUMENT_EMBEDDING` |
| `RERANK` | 检索结果重排模型 | `RETRIEVAL_RERANK` |

服务类型为稳定业务枚举：

| 服务类型 | 页面名称 | 是否必配 | 未配置行为 |
|---|---|---|---|
| `QA` | 智能问答 | 是 | 禁止启用问答生成，返回配置缺失错误 |
| `DOCUMENT_CLASSIFICATION` | 文档自动分类 | 是 | 文档进入待确认，不参与查询 |
| `DOCUMENT_EMBEDDING` | 文档向量化 | 是 | Embedding 任务失败并等待配置修复后重试 |
| `RETRIEVAL_RERANK` | 检索重排 | 否 | 降级使用融合检索顺序 |

“是否必配”表示对应业务投入使用前必须配置，不表示首次打开页面时强迫管理员一次填完全部字段。

## 5. 页面信息架构

页面继续使用当前系统管理布局和 `PageHeader`：

```text
LLM 配置
管理模型连接，并为各项 AI 服务选择使用的模型。

[模型管理] [服务配置]
```

Tab 状态只影响页面展示，不改变路由。刷新页面默认进入“模型管理”；如需支持深链接，可使用查询参数 `?tab=models` 和 `?tab=services`，不增加子路由。

## 6. Tab 一：模型管理

### 6.1 页面结构

```text
模型管理                                              [添加模型]

名称              类型          Model             状态       操作
内网 Qwen         Chat          Qwen3-32B         已启用     测试连接｜编辑｜停用
向量模型          Embedding     bge-m3            已启用     测试连接｜编辑｜停用
重排模型          Rerank        bge-reranker-v2   已停用     测试连接｜编辑｜启用
```

列表列定义：

| 列 | 内容 |
|---|---|
| 名称 | 管理员维护的配置名称 |
| 类型 | Chat、Embedding 或 Rerank |
| Model | 上游接口需要的真实模型名称 |
| 服务商 | 协议/适配器名称；窄屏时可与类型合并展示 |
| 状态 | 已启用、已停用 |
| 操作 | 测试连接、编辑、启用或停用 |

空状态文案：`暂无模型配置。添加模型后，可在“服务配置”中将它用于具体业务。`

### 6.2 新增和编辑表单

| 字段 | API 字段 | 必填 | 规则 |
|---|---|---:|---|
| 配置名称 | `name` | 是 | 1～128 字符；用于管理员识别，同名不允许重复 |
| 模型类型 | `model_type` | 是 | `CHAT`、`EMBEDDING`、`RERANK` |
| 服务商/协议 | `provider` | 是 | V1 为受控枚举，至少支持 `openai-compatible` |
| Base URL | `base_url` | 是 | HTTP/HTTPS URL；保存时移除末尾 `/` |
| Model 名称 | `model_name` | 是 | 1～128 字符；原样发送给上游 |
| API Key | `api_key` | 条件必填 | 服务需要鉴权时填写；编辑留空表示保持不变 |
| 启用状态 | `enabled` | 是 | 新增默认启用 |

API Key 的编辑语义：

- 字段缺失或 `null`：保持当前密钥；
- 非空字符串：替换密钥；
- V1 页面不提供清除密钥的快捷操作；如后续需要，使用独立确认操作，避免把误留空解释为删除。

不在表单中展示：温度、Top P、最大 Token、超时、重试次数、主备角色。

### 6.3 模型类型修改

未被服务引用的模型允许修改类型；已被服务引用时禁止修改类型，并提示：

`该模型正在被服务使用。请先在“服务配置”中解除或更换绑定。`

### 6.4 启用与停用

- 启用前必须通过字段校验，但不强制最近一次连接测试成功；
- 未被服务引用的模型可直接停用；
- 被服务引用的模型不允许直接停用；
- 操作返回冲突时，页面提示受影响的服务名称，并提供“前往服务配置”；
- V1 不提供删除，避免误删密钥和破坏历史 revision 的可解释性。

### 6.5 连接测试

连接测试属于模型管理，不改变配置状态，也不自动保存或绑定服务。

按模型类型发送受控最小请求：

| 类型 | 测试方式 | 成功判定 |
|---|---|---|
| CHAT | 最短对话请求 | 2xx 且响应结构可解析 |
| EMBEDDING | 对固定短文本生成向量 | 2xx、存在非空数值向量，并返回维度 |
| RERANK | 对固定查询和两个短候选重排 | 2xx 且返回可解析的排序或分数 |

测试结果只展示：成功/失败、耗时、必要的错误分类；不得把上游原始响应、Authorization、API Key 或完整响应正文返回浏览器或写入审计日志。

服务地址必须执行 DD-12 的 SSRF 防护：生产环境采用已登记 Endpoint 或网络白名单，禁止访问环回、链路本地和云元数据地址；禁止跟随到非白名单地址的重定向。

## 7. Tab 二：服务配置

### 7.1 页面结构

```text
服务配置

智能问答
用于知识查询的答案生成。
[内网 Qwen / Qwen3-32B                              v]

文档自动分类
用于判断文档相关性并生成分类建议。
[内网 Qwen / Qwen3-32B                              v]

文档向量化
用于生成知识库向量索引。
[向量模型 / bge-m3                                  v]

检索重排
可选；未配置时使用融合检索顺序。
[暂不启用                                            v]

                                                     [保存配置]
```

### 7.2 选择规则

- 下拉框只展示已启用模型；
- `QA` 和 `DOCUMENT_CLASSIFICATION` 只展示 `CHAT`；
- `DOCUMENT_EMBEDDING` 只展示 `EMBEDDING`；
- `RETRIEVAL_RERANK` 只展示 `RERANK`，并包含“暂不启用”；
- 选项显示 `配置名称 / Model 名称`，避免同一 Model 在不同 Endpoint 下无法区分；
- 模型在加载页面后被其他管理员停用时，保存必须由后端再次校验并返回 `409`。

### 7.3 Embedding 变更确认

当 `DOCUMENT_EMBEDDING` 从已有模型切换到另一模型时，保存前展示确认提示：

`更换 Embedding 模型后，现有向量索引不能直接复用，需要创建新的索引 generation 并重新向量化。是否继续保存？`

确认保存只更新服务绑定，不在同一请求中启动全量重建。保存成功后页面展示明确的后续状态或入口；索引 generation 的创建和任务调度由 DD-04、DD-06、DD-07 定义。

如果两个配置指向相同模型名称，也不能仅凭名称认定向量兼容。V1 一律按模型配置 ID 变化触发提示。

### 7.4 未保存修改

- 切换 Tab 时保留当前未保存选择；
- 离开页面或刷新时，如存在未保存修改，使用统一离开确认；
- 保存成功后重新读取服务绑定，页面以服务端结果为准；
- 保存失败不清除用户当前选择。

## 8. 数据设计

### 8.1 V1 存储策略

考虑当前平台规模和现有架构，V1 不新增模型网关专用关系表，复用：

- `platform.config_revisions`：保存模型列表和服务绑定的版本快照；
- `platform.secret_values`：保存每个模型配置的 API Key 密文。

使用一个 namespace：`llm`。单个 ACTIVE revision 的 `content` 结构为：

```json
{
  "schema_version": 2,
  "models": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "内网 Qwen",
      "model_type": "CHAT",
      "provider": "openai-compatible",
      "base_url": "https://llm.intra/v1",
      "model_name": "Qwen3-32B",
      "enabled": true
    }
  ],
  "service_bindings": {
    "QA": "550e8400-e29b-41d4-a716-446655440000",
    "DOCUMENT_CLASSIFICATION": "550e8400-e29b-41d4-a716-446655440000",
    "DOCUMENT_EMBEDDING": null,
    "RETRIEVAL_RERANK": null
  }
}
```

模型 ID 一经创建保持稳定；编辑模型产生新 revision，但不改变 ID，因此服务绑定无需重写。

### 8.2 密钥定位

`secret_values` 使用：

```text
namespace = "llm_model"
key_name  = <model_config_id>
```

配置 revision 只根据是否存在对应 SecretValue 计算 `has_api_key`，绝不保存密钥明文、密文或密钥摘要。

### 8.3 revision 与事务

任何会改变模型或绑定的操作必须在同一事务内：

1. 读取当前 ACTIVE revision；
2. 完成业务校验；
3. 将当前 revision 标记为 `RETIRED`；
4. 写入新的 ACTIVE revision；
5. 如涉及密钥，同事务更新 SecretValue；
6. 写入成功审计事件；
7. 统一提交。

并发更新依靠“同一 namespace 只有一个 ACTIVE revision”的唯一约束兜底。API 应支持 `expected_revision`，与当前 revision 不一致时返回：

```json
{
  "code": "CONFIG_VERSION_CONFLICT",
  "message": "配置已被其他管理员修改，请刷新后重试"
}
```

## 9. API 设计

所有接口位于 `/api/v1/admin/llm-config`，仅管理员可访问。

### 9.1 模型管理 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/models` | 获取模型列表 |
| POST | `/models` | 新增模型 |
| PATCH | `/models/{model_id}` | 编辑模型 |
| POST | `/models/{model_id}/enable` | 启用模型 |
| POST | `/models/{model_id}/disable` | 停用模型 |
| POST | `/models/test` | 测试尚未保存或正在编辑的模型配置 |

模型列表响应示例：

```json
{
  "data": {
    "revision": 12,
    "items": [
      {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "name": "内网 Qwen",
        "model_type": "CHAT",
        "provider": "openai-compatible",
        "base_url": "https://llm.intra/v1",
        "model_name": "Qwen3-32B",
        "enabled": true,
        "has_api_key": true,
        "used_by": ["QA", "DOCUMENT_CLASSIFICATION"]
      }
    ]
  }
}
```

新增/编辑请求包含 `expected_revision`。编辑时 `api_key: null` 表示保持不变。

### 9.2 服务配置 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/service-bindings` | 获取当前业务服务绑定及可选模型 |
| PUT | `/service-bindings` | 原子保存全部服务绑定 |

保存请求示例：

```json
{
  "expected_revision": 12,
  "bindings": {
    "QA": "550e8400-e29b-41d4-a716-446655440000",
    "DOCUMENT_CLASSIFICATION": "550e8400-e29b-41d4-a716-446655440000",
    "DOCUMENT_EMBEDDING": "7ecb89a0-57ab-4fe3-a4b5-d101442331e1",
    "RETRIEVAL_RERANK": null
  }
}
```

后端必须原子校验全部绑定；任一绑定不合法时不保存任何一项。

### 9.3 测试接口语义

测试请求允许两种密钥来源：

- 请求携带新的非空 `api_key`：测试该值，但不保存；
- 请求 `api_key` 为 `null` 且携带 `model_id`：使用已保存密钥；

不得通过空字符串隐式清除密钥。测试结果采用稳定错误码，例如：

- `MODEL_TEST_TIMEOUT`
- `MODEL_TEST_AUTH_FAILED`
- `MODEL_TEST_NOT_FOUND`
- `MODEL_TEST_PROTOCOL_ERROR`
- `MODEL_TEST_NETWORK_ERROR`

## 10. 错误码

| 错误码 | HTTP | 场景 |
|---|---:|---|
| `MODEL_CONFIG_NOT_FOUND` | 404 | 模型配置不存在 |
| `MODEL_CONFIG_NAME_DUPLICATE` | 409 | 配置名称重复 |
| `MODEL_CONFIG_IN_USE` | 409 | 停用或修改类型时仍被服务引用 |
| `MODEL_CONFIG_DISABLED` | 409 | 服务绑定选择了停用模型 |
| `MODEL_TYPE_MISMATCH` | 409 | 服务与模型类型不匹配 |
| `REQUIRED_SERVICE_MODEL_MISSING` | 409 | 必配服务未选择模型 |
| `CONFIG_VERSION_CONFLICT` | 409 | revision 已变化 |
| `INVALID_MODEL_ENDPOINT` | 422 | Endpoint 格式或安全校验失败 |

## 11. 运行时读取

分类器、问答、Embedding 和 Rerank 业务不得自行读取页面字段或拼装模型名称，统一通过配置服务按 `service_type` 解析：

```text
service_type
  -> ACTIVE llm revision
  -> service_bindings[service_type]
  -> models[id]
  -> SecretValue(namespace="llm_model", key_name=id)
  -> Model Gateway / HTTP adapter
```

一次业务调用开始时解析并固定 revision 与 model ID；调用过程中即使管理员发布新配置，也不改变本次调用。运行记录至少保存：

- `config_revision`；
- `service_type`；
- `model_config_id`；
- `provider`；
- `actual_model_name`；
- 成功/失败、耗时和 Token（如上游提供）。

## 12. 旧配置迁移

旧版 `llm` revision 为单条结构，包含 `model`、`classification_model`、`embedding_model` 和全局连接信息。迁移到 `schema_version=2` 时：

1. `model` 非空：创建一个 `CHAT` 模型并绑定 `QA`；
2. `classification_model` 非空：创建或复用同名同 Endpoint 的 `CHAT` 模型并绑定 `DOCUMENT_CLASSIFICATION`；
3. `embedding_model` 非空：创建一个 `EMBEDDING` 模型并绑定 `DOCUMENT_EMBEDDING`；
4. 旧版没有 Rerank 字段，`RETRIEVAL_RERANK` 设为 `null`；
5. 旧 `enabled=false` 时，迁移模型保持停用，服务绑定仍可保存但业务运行前必须完成启用校验；
6. 旧全局 API Key 密文复制到迁移生成的模型 SecretValue，确认新密钥可读取后再删除旧 `llm/api_key`；
7. 迁移脚本必须可重复执行，检测到 `schema_version >= 2` 时不重复生成模型；
8. 旧 revision 保留为 `RETIRED`，用于审计和回溯。

如果旧配置为空，只创建 `schema_version=2` 的空模型列表和空绑定，不生成占位模型。

旧 `/api/v1/admin/llm-config` 单对象 GET/PUT 和 `/test` 接口在新前端切换后停止使用。V1 为内部系统，可在同一版本删除旧契约；若部署需要滚动升级，则旧接口保留只读兼容一个发布周期，禁止新旧写接口并存。

## 13. 审计要求

新增稳定动作码：

| 动作码 | 风险 | 审计字段 |
|---|---|---|
| `config.llm.model.create` | 高 | name、model_type、provider、base_url、model_name、enabled、has_api_key |
| `config.llm.model.update` | 高 | 同上，仅记录发生变化的字段 |
| `config.llm.model.enable` | 高 | enabled |
| `config.llm.model.disable` | 高 | enabled、used_by |
| `config.llm.binding.update` | 高 | 各 service_type 的 before/after model ID |

连接测试记录系统日志和管理员、目标模型、结果、耗时，不记录为配置变更；不得记录 API Key、请求正文、Prompt 或上游响应正文。

## 14. 测试设计

### 14.1 后端测试

| 编号 | 场景 | 期望 |
|---|---|---|
| TC-MC-001 | 新增 CHAT 模型 | 返回模型 ID，revision 增长，密钥不回显 |
| TC-MC-002 | 编辑模型时 `api_key=null` | 原密钥保持不变 |
| TC-MC-003 | 同名模型重复新增 | 返回 409，不产生新 revision |
| TC-MC-004 | 停用未引用模型 | 成功并产生新 revision |
| TC-MC-005 | 停用已引用模型 | 返回 `MODEL_CONFIG_IN_USE` |
| TC-MC-006 | QA 绑定 CHAT | 保存成功 |
| TC-MC-007 | QA 绑定 EMBEDDING | 返回 `MODEL_TYPE_MISMATCH`，全部绑定不变 |
| TC-MC-008 | 绑定停用模型 | 返回 `MODEL_CONFIG_DISABLED` |
| TC-MC-009 | 两管理员使用同一 revision 保存 | 后提交者返回 `CONFIG_VERSION_CONFLICT` |
| TC-MC-010 | GET 模型列表 | 响应和日志均不包含密钥明文或密文 |
| TC-MC-011 | CHAT/Embedding/Rerank 测试 | 分别验证正确的最小协议和错误映射 |
| TC-MC-012 | 旧配置迁移执行两次 | 第二次无新增数据，结果一致 |

### 14.2 前端测试

| 编号 | 场景 | 期望 |
|---|---|---|
| TC-MC-FE-001 | 切换两个 Tab | 数据和未保存状态符合第 7.4 节 |
| TC-MC-FE-002 | 新增模型 | 只展示 V1 必要字段 |
| TC-MC-FE-003 | 服务选择器 | 只显示启用且类型匹配的模型 |
| TC-MC-FE-004 | 切换 Embedding | 保存前出现重建索引确认 |
| TC-MC-FE-005 | 停用被引用模型 | 展示受影响服务和跳转入口 |
| TC-MC-FE-006 | revision 冲突 | 提示刷新，不覆盖其他管理员修改 |

### 14.3 验收标准

- 管理员无需理解主备、路由、温度和重试即可完成配置；
- 模型连接信息只在模型管理维护一次；
- 同一 CHAT 模型能够同时绑定问答和分类；
- 类型不匹配、停用模型和并发覆盖均由后端阻止；
- API Key 在任何读取响应、审计和普通日志中不出现；
- Embedding 变更不会被当作普通 Chat 模型切换静默处理；
- 后续 Agent 能依据本文完成数据库迁移、后端 API、前端交互和自动化测试，无需重新决定产品边界。

## 15. 实施顺序

1. 增加 `schema_version=2` 配置 Schema 和旧配置迁移；
2. 实现模型管理服务、密钥读写和 revision 冲突控制；
3. 实现服务绑定校验和运行时解析器；
4. 实现新管理 API 和审计动作；
5. 将现有 LLM 配置页改为两个 Tab；
6. 接入分类、问答、Embedding、Rerank 运行时；
7. 补齐后端、前端和迁移测试；
8. 删除或冻结旧单对象配置接口。

## 16. 后续扩展点

如未来需要备用模型，在 `service_bindings` 的单个值上向兼容结构演进：

```json
{
  "QA": {
    "primary_model_id": "...",
    "fallback_model_id": null
  }
}
```

备用模型保持可选，并由系统内置可重试错误范围。除非有实际容量或可靠性证据，V1 不提前实现权重、负载均衡和复杂路由策略。
