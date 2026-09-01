"""Request schemas shared by capability administration routes."""

from pydantic import BaseModel, Field, HttpUrl


class EnabledPatch(BaseModel):
    enabled: bool


class SkillCreate(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    description: str = Field(min_length=1, max_length=1024)
    content: str = Field(min_length=1)
    version: str = Field(default="1.0.0", max_length=32)
    enabled: bool = True


class McpCreate(BaseModel):
    name: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]{1,63}$")
    endpoint: HttpUrl
    description: str = Field(default="", max_length=1024)
    transport: str = Field(default="STREAMABLE_HTTP", pattern=r"^(STREAMABLE_HTTP|SSE)$")
    auth_type: str = Field(default="NONE", pattern=r"^(NONE|OAUTH2|BEARER)$")
    enabled: bool = False
