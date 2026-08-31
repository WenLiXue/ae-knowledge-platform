from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """后端运行配置，始终从 backend/.env 或环境变量读取。"""

    # 不能使用相对路径：uvicorn 可能从项目根目录启动，而 .env 位于 backend/ 下。
    model_config = SettingsConfigDict(
        env_file=str(_BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = (
        "postgresql+psycopg://ae_knowledge:ae_knowledge_dev@localhost:5432/ae_knowledge"
    )
    # 登录尚未实现，提交的来源暂记在系统默认用户名下；接入真实认证后改为请求者
    default_owner_user_id: str = "11111111-1111-1111-1111-111111111111"
    # development / production：production 下不暴露开发辅助能力
    environment: str = "development"

    # 运行日志
    # log_json=None：按 environment 推导（production 用 JSON，development 人类可读）
    log_level: str = "INFO"
    log_json: bool | None = None
    # 是否把 ERROR+ 日志 best-effort 持久化到 platform.log_events
    log_persist_errors: bool = True

    # ---- 分类与 RAG 功能开关（DD-19 Phase 0） ----
    # 真实能力逐阶段上线：默认全部关闭，仅走 Mock/旧流程；每个开关
    # 在对应 Phase（分类 Phase 3、索引 Phase 4、问答 Phase 6）启用时才打开。
    # 打开前必须满足该 Phase 的验收标准，并确认回滚边界。
    feature_real_classification: bool = False
    feature_real_indexing: bool = False
    feature_real_qa: bool = False

    # 任务 Worker 配置
    # 留空时由 Worker 使用容器 hostname 生成唯一实例 ID；多副本部署不能共享固定 ID。
    worker_id: str = ""
    worker_batch_size: int = 5
    worker_poll_interval_seconds: float = 2.0
    # 租约秒数：超过未心跳/未完成的任务可被其他 Worker 回收
    lease_seconds: int = 60
    # 重试退避基数（秒）：delay = base * 2 ** (attempt - 1)；测试可传 0 使重试立即可领取
    retry_base_delay_seconds: float = 1.0
    # 回答超过该时长仍处于进行中状态时，读取接口会将其标记为失败，避免前端永久转圈。
    answer_stale_timeout_seconds: int = 900

    # ---- LangGraph 知识助手 Agent（DD-21） ----
    # 初始关闭：新任务走旧 qa.worker 编排；灰度和验收通过后再开启（DD-21 §19 阶段 D）。
    agent_graph_enabled: bool = False
    agent_graph_version: str = "knowledge-assistant-v1"
    # Tool-Agent rollout flags. Disabled by default so DD-21 remains the
    # production fallback until the new execution path passes its gates.
    agent_tools_enabled: bool = False
    agent_planner_enabled: bool = False
    agent_write_tools_enabled: bool = False
    agent_max_plan_steps: int = 8
    agent_max_tool_calls: int = 10
    agent_max_replans: int = 1
    agent_planner_timeout_seconds: float = 15.0
    agent_rerank_timeout_seconds: float = 8.0
    agent_parallel_read_limit: int = 3
    agent_task_timeout_seconds: int = 180
    agent_tool_result_max_bytes: int = 65536
    agent_approval_ttl_minutes: int = 30
    # 单次 answer run 图总步数（节点执行数）硬限制。
    # 最坏合法流程（一次 query rewrite + 一次 citation repair）约 14 个节点，
    # 默认 16 为实施起点，可经黄金问题集调优（DD-21 §13）。
    agent_max_steps: int = 16
    # 单次 answer run 总截止时间（秒）；每次 Worker 重试按新 attempt 重新起算
    agent_timeout_seconds: int = 90
    # 各类修复上限：意图 Schema / 检索 query rewrite / 引用修复 / 记忆 Schema
    agent_intent_repair_limit: int = 1
    agent_query_rewrite_limit: int = 1
    agent_citation_repair_limit: int = 1
    agent_memory_repair_limit: int = 1
    # 会话记忆 token 预算（DD-21 §8.3）
    conversation_recent_token_budget: int = 6000
    conversation_summary_token_budget: int = 1500
    conversation_compaction_trigger_ratio: float = 0.70
    # LangGraph checkpoint 连接串；空则复用业务库 database_url（独立 agent_runtime schema）
    agent_checkpoint_dsn: str = ""
    # 成功 checkpoint 保留天数（异步清理）；失败运行保留更长时间便于排查
    agent_checkpoint_retention_days: int = 14
    agent_checkpoint_failed_retention_days: int = 30
    # 生成模型上下文窗口与输出预留（未配置模型能力字段时的保守默认，DD-21 §23）
    agent_default_context_window: int = 32768
    agent_reserved_output_tokens: int = 2048
    # 受控脱敏采样日志（DD-21 §17.1，V1 默认关闭）：开启后 agent 日志包含
    # 截断的提问/答案预览（question_preview ≤120 字、answer_preview ≤200 字），
    # 便于排查；仍不记录完整问题、证据正文、提示词与密钥。
    agent_log_payloads: bool = False

    # 飞书文档接入
    # fake：使用 FakeFeishuProvider（开发/测试默认）；real：接入真实飞书 API（需应用凭据与用户 OAuth）
    feishu_provider: str = "fake"
    # 凭据禁止写入源码；真实环境必须在 backend/.env 或系统环境变量中配置。
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_base_url: str = "https://open.feishu.cn"
    feishu_timeout_seconds: float = 10.0
    # 本地对象存储根目录（对象存储接入前，Worker FETCH 的 raw 内容落盘位置）
    storage_root: str = "storage"

    # 检索引擎与向量化（DD-19 §11.2，Phase 4）
    # search_engine=fake：内存实现（开发/测试）；pgvector：PostgreSQL 向量检索（生产首选）
    search_engine: str = "pgvector"
    search_index_name: str = "knowledge_chunks"
    opensearch_base_url: str = ""
    opensearch_username: str = ""
    opensearch_password: str = ""
    # 文档向量化单批最大条数（EMBED 阶段）
    embedding_batch_size: int = 32

    # 飞书 OAuth / 用户绑定（凭据仅从 .env/环境变量读取，禁止写入代码）
    # 授权/登录 host（扫码登录 passport 授权地址前缀）
    feishu_passport_host: str = "https://passport.feishu.cn/suite/passport/oauth/"
    # 后端 OAuth 回调地址，需在飞书后台「安全设置 → 重定向 URL」登记一致
    feishu_redirect_uri: str = "http://127.0.0.1:8000/api/v1/auth/feishu/callback"
    # 绑定成功后浏览器跳转的前端地址
    feishu_frontend_redirect_uri: str = "http://127.0.0.1:5173"
    # 会话 Cookie 名与有效期（小时）
    session_cookie_name: str = "ae_session"
    session_ttl_hours: int = 24
    # Production defaults to Secure; set false for an internal HTTP deployment.
    session_cookie_secure: bool | None = None
    # 凭据信封加密密钥（base64 编码 32 字节；生产必须用密钥管理/部署环境变量覆盖）
    token_enc_key: str = "ZGV2LW9ubHktdG9rZW4tZW5jLWtleS0zMi1ieXRlcyE="

    # ---- 操作审计（DD-17） ----
    # 审计记录 HMAC 密钥（record_hash）。运行环境提供，禁止入库；开发默认值仅用于本地/测试。
    audit_hmac_key: str = "dev-only-audit-hmac-key"
    # 审计导出文件落盘目录（相对项目根或绝对路径）
    audit_export_dir: str = "exports"
    # 审计导出文件保留时长（小时），过期后文件删除、不可下载
    audit_export_ttl_hours: int = 24
    # 单次导出最大条数
    audit_export_max_rows: int = 100_000
    # 可信反向代理转发头（如 "x-forwarded-for"）。为空时不信任任何转发头，来源 IP 取实际连接地址。
    audit_trusted_proxy_header: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
