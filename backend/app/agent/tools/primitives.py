"""Small, read-only primitives for agent composition.

These tools never execute shell commands and reject paths outside the runtime
allowed roots. Higher-level Skills should compose them for domain workflows.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from ..contracts.tool import ToolDefinition, ToolResultEnvelope
from .base import ToolContext, ToolError


def _safe_path(raw: str, context: ToolContext) -> Path:
    candidate = Path(raw).expanduser().resolve()
    roots = context.metadata.get("allowed_roots") or ["/app/backend/storage"]
    allowed = [Path(str(root)).expanduser().resolve() for root in roots]
    if not any(candidate == root or root in candidate.parents for root in allowed):
        raise ToolError("PATH_ACCESS_DENIED", "路径不在允许访问范围内")
    return candidate


class FileReadInput(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    max_bytes: int = Field(default=128_000, ge=1, le=1_000_000)


class FileReadTool:
    input_model = FileReadInput
    output_model = FileReadInput
    definition = ToolDefinition(
        name="file.read", version="1.0", description="读取允许范围内的文本文件内容。",
        input_schema=FileReadInput.model_json_schema(), output_schema={"type": "object"},
        layer="PRIMITIVE", owner="platform", risk="READ_ONLY", side_effect=False,
        requires_confirmation=False, idempotency="NOT_APPLICABLE", required_permissions=["filesystem:read"],
        timeout_seconds=10, max_retries=0, max_result_bytes=1_000_000, sensitivity="RESTRICTED",
    )

    def execute(self, args: FileReadInput, context: ToolContext) -> ToolResultEnvelope:
        path = _safe_path(args.path, context)
        if not path.is_file():
            raise ToolError("FILE_NOT_FOUND", "文件不存在")
        try:
            content = path.read_text(encoding="utf-8")[: args.max_bytes]
        except UnicodeDecodeError as exc:
            raise ToolError("FILE_NOT_TEXT", "文件不是 UTF-8 文本") from exc
        now = datetime.now(timezone.utc)
        return ToolResultEnvelope(call_id=str(context.metadata.get("call_id") or uuid.uuid4()), tool_name=self.definition.name,
            tool_version=self.definition.version, status="SUCCEEDED", data={"path": str(path), "content": content},
            summary="已读取文件", truncated=path.stat().st_size > args.max_bytes, sensitivity=self.definition.sensitivity,
            started_at=now, completed_at=datetime.now(timezone.utc))


class FileListInput(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    pattern: str = Field(default="*", max_length=128)


class FileListTool:
    input_model = FileListInput
    output_model = FileListInput
    definition = FileReadTool.definition.model_copy(update={
        "name": "file.list", "description": "列出允许范围内目录中的文件。",
        "input_schema": FileListInput.model_json_schema(), "max_result_bytes": 128_000,
    })

    def execute(self, args: FileListInput, context: ToolContext) -> ToolResultEnvelope:
        path = _safe_path(args.path, context)
        if not path.is_dir():
            raise ToolError("DIRECTORY_NOT_FOUND", "目录不存在")
        items = [{"name": p.name, "path": str(p), "is_dir": p.is_dir()} for p in sorted(path.glob(args.pattern))[:1000]]
        now = datetime.now(timezone.utc)
        return ToolResultEnvelope(call_id=str(context.metadata.get("call_id") or uuid.uuid4()), tool_name=self.definition.name,
            tool_version=self.definition.version, status="SUCCEEDED", data={"items": items}, summary=f"找到 {len(items)} 个条目",
            sensitivity=self.definition.sensitivity, started_at=now, completed_at=datetime.now(timezone.utc))


class TextGrepInput(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    pattern: str = Field(min_length=1, max_length=500)
    max_matches: int = Field(default=100, ge=1, le=1000)


class TextGrepTool:
    input_model = TextGrepInput
    output_model = TextGrepInput
    definition = FileReadTool.definition.model_copy(update={
        "name": "text.grep", "description": "在允许范围内的文本文件中搜索正则表达式。",
        "input_schema": TextGrepInput.model_json_schema(), "max_result_bytes": 256_000,
    })

    def execute(self, args: TextGrepInput, context: ToolContext) -> ToolResultEnvelope:
        path = _safe_path(args.path, context)
        if not path.is_file():
            raise ToolError("FILE_NOT_FOUND", "文件不存在")
        try:
            regex = re.compile(args.pattern)
            lines = path.read_text(encoding="utf-8").splitlines()
        except (re.error, UnicodeDecodeError) as exc:
            raise ToolError("GREP_INVALID_INPUT", "搜索表达式或文件编码无效") from exc
        matches = [{"line": i, "text": line} for i, line in enumerate(lines, 1) if regex.search(line)][:args.max_matches]
        now = datetime.now(timezone.utc)
        return ToolResultEnvelope(call_id=str(context.metadata.get("call_id") or uuid.uuid4()), tool_name=self.definition.name,
            tool_version=self.definition.version, status="SUCCEEDED", data={"matches": matches}, summary=f"找到 {len(matches)} 处匹配",
            sensitivity=self.definition.sensitivity, started_at=now, completed_at=datetime.now(timezone.utc))


def register_primitive_tools(registry) -> None:
    registry.register(FileReadTool())
    registry.register(FileListTool())
    registry.register(TextGrepTool())
