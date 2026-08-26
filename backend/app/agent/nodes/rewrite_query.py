"""rewrite_query：只改写检索表达；最多一次；不扩大用户授权与过滤范围。"""

from __future__ import annotations

REWRITE_SYSTEM_PROMPT = (
    "你是检索查询改写器。只改写检索表达本身，不改变用户的问题边界与授权范围。"
    '只输出一个 JSON 对象：{"rewritten_query": string}。'
)


def core_rewrite_query(state: dict, ctx):
    count = state.get("query_rewrite_count", 0)
    if count >= ctx.settings.agent_query_rewrite_limit:
        return {}
    question = state.get("normalized_question") or state.get("question") or ""
    new_query = question
    if ctx.settings.feature_real_qa:
        try:
            content = ctx.models.chat(
                [
                    {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"原问题：{question}\n检索结果不足。请改写为一个更精确的检索表达式。",
                    },
                ]
            )
            import json

            text = content.strip()
            if text.startswith("```"):
                text = "\n".join(text.splitlines()[1:])
                if text.rstrip().endswith("```"):
                    text = text.rstrip()[:-3].rstrip()
            start, end = text.find("{"), text.rfind("}")
            if start != -1 and end > start:
                data = json.loads(text[start : end + 1])
                rewritten = str(data.get("rewritten_query") or "").strip()
                if rewritten:
                    new_query = rewritten
        except Exception:  # noqa: BLE001 改写失败保持原问题
            pass
    return {
        "query_rewrite_count": count + 1,
        "normalized_question": new_query,
        "route_reason_code": "QUERY_REWRITTEN",
        "degradation_flags": _merge(state.get("degradation_flags", []), ["QUERY_REWRITTEN"]),
    }


def _merge(flags: list[str], extra: list[str]) -> list[str]:
    seen = list(flags)
    for flag in extra:
        if flag and flag not in seen:
            seen.append(flag)
    return seen
