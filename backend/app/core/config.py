from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """后端运行配置，读取 backend/.env（见 .env.example）。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://ae_knowledge:ae_knowledge_dev@localhost:5432/ae_knowledge"
    )
    # 登录尚未实现，提交的来源暂记在系统默认用户名下；接入真实认证后改为请求者
    default_owner_user_id: str = "11111111-1111-1111-1111-111111111111"
    # development / production：production 下不暴露开发辅助能力
    environment: str = "development"

    # 任务 Worker 配置
    worker_id: str = "worker-local"
    worker_batch_size: int = 5
    worker_poll_interval_seconds: float = 2.0
    # 租约秒数：超过未心跳/未完成的任务可被其他 Worker 回收
    lease_seconds: int = 60
    # 重试退避基数（秒）：delay = base * 2 ** (attempt - 1)；测试可传 0 使重试立即可领取
    retry_base_delay_seconds: float = 1.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
