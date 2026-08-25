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

    # 任务 Worker 配置
    worker_id: str = "worker-local"
    worker_batch_size: int = 5
    worker_poll_interval_seconds: float = 2.0
    # 租约秒数：超过未心跳/未完成的任务可被其他 Worker 回收
    lease_seconds: int = 60
    # 重试退避基数（秒）：delay = base * 2 ** (attempt - 1)；测试可传 0 使重试立即可领取
    retry_base_delay_seconds: float = 1.0

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
