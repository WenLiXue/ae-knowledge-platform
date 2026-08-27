"""Answer questions about the authenticated principal from runtime context."""

from __future__ import annotations


def core_answer_identity(state: dict, ctx):
    """Render identity without retrieval, memory, or tool planning."""
    principal = ctx.principal
    if principal is None:
        return {
            "_terminate": True,
            "final_status": "FAILED",
            "error_code": "PRINCIPAL_CONTEXT_UNAVAILABLE",
            "error_summary": "无法读取当前登录用户上下文",
        }

    role = "管理员" if principal.is_admin else "普通用户"
    account = f"（账号：{principal.username}）" if principal.username else ""
    return {
        "final_status": "SUCCEEDED",
        "answer_type": "ANSWER",
        "answer_summary": (
            f"你当前登录的身份是 {principal.display_name}{account}，"
            f"角色为{role}，账号状态为{principal.status}。"
        ),
        "answer_blocks": [],
        "citation_drafts": [],
        "degradation_flags": [],
    }
