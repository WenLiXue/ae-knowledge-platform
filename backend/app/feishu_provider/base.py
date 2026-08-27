"""飞书文档提供者抽象。

Worker 与 API 只依赖 FeishuDocumentProvider 接口，不直接依赖飞书 SDK。
接入真实飞书时，把工厂配置切换到 RealFeishuProvider 即可，阶段契约不变。

方法统一接收 user_access_token（来自用户飞书绑定的凭据，由 OAuth 提供）；
Fake 实现忽略该参数。真实调用方负责解析当前用户的 token，不向前端暴露。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

# 错误分类（对齐 DD-02 §8.2，语义与 PipelineError.category 一致）
AUTH = "AUTH"                 # 授权失效/凭据无效，不可重试
NOT_FOUND = "NOT_FOUND"       # 文档被删除或无权访问，不可重试
PERMISSION = "PERMISSION"     # 无权限读取，归入授权问题，不可重试
RATE_LIMIT = "RATE_LIMIT"     # 飞书接口限流，可重试
TIMEOUT = "TIMEOUT"           # 网络/服务超时，可重试
TRANSIENT = "TRANSIENT"       # 其他瞬时错误（5xx 等），可重试
VALIDATION = "VALIDATION"     # 参数/格式错误，不可重试


class FeishuError(Exception):
    """飞书调用失败，携带稳定的错误分类与 code。"""

    def __init__(self, category: str, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.category = category
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass
class FeishuDocument:
    """飞书文档元数据（发现/解析/提交用）。"""

    resource_token: str          # 规范化底层 token（Wiki 取其指向的底层资源 token）
    title: str
    resource_type: str           # "wiki" / "docx" / "sheet" / "file" 等
    canonical_token: str = ""    # 去重用键，默认等于 resource_token
    modified_at: datetime | None = None
    owner_name: str | None = None
    url: str | None = None
    node_token: str | None = None
    revision: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class FeishuContent:
    """文档正文与版本信息（Worker FETCH 的产物）。"""

    title: str
    text: str                    # 规范化正文（纯文本/Markdown）
    content_type: str = "docx"   # "wiki" / "docx" / "sheet"
    revision: str | None = None
    modified_at: datetime | None = None
    raw_payload: dict = field(default_factory=dict)  # 完整原始 JSON，写入 raw 对象


@dataclass
class FeishuListResult:
    items: list[FeishuDocument]
    next_cursor: str | None = None


class FeishuDocumentProvider(ABC):
    """文档发现与读取的统一入口。"""

    @abstractmethod
    def list_documents(
        self,
        *,
        user_access_token: str | None,
        query: str | None = None,
        resource_types: list[str] | None = None,
        page_token: str | None = None,
        limit: int = 20,
    ) -> FeishuListResult:
        """发现当前用户可见的文档元数据。"""

    @abstractmethod
    def resolve_url(self, user_access_token: str | None, url: str) -> FeishuDocument:
        """把用户粘贴的 Docx/Wiki URL 解析为底层资源与 token。"""

    @abstractmethod
    def get_metadata(
        self, user_access_token: str | None, resource_token: str, resource_type: str
    ) -> FeishuDocument:
        """获取单个文档元数据（标题/修改时间/所有者/revision）。"""

    @abstractmethod
    def fetch_content(
        self,
        user_access_token: str | None,
        resource_token: str,
        resource_type: str,
        *,
        source_url: str | None = None,
    ) -> FeishuContent:
        """读取文档正文与版本信息。"""
