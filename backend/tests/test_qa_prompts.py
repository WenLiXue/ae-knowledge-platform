from app.qa.prompts import (
    GENERAL_GENERATION_SYSTEM_PROMPT,
    GENERATION_SYSTEM_PROMPT,
    UNDERSTANDING_SYSTEM_PROMPT,
)


def test_explain_prompt_routes_common_acronyms_without_forced_retrieval() -> None:
    assert "行业术语或缩写" in UNDERSTANDING_SYSTEM_PROMPT
    assert "即使该术语承接上一轮产品问题" in UNDERSTANDING_SYSTEM_PROMPT
    assert "通俗语言先给出通常含义" in GENERAL_GENERATION_SYSTEM_PROMPT


def test_grounded_prompt_forbids_claiming_partial_list_is_complete() -> None:
    assert "完整条目索引" in GENERATION_SYSTEM_PROMPT
    assert "不得根据局部证据推断总数" in GENERATION_SYSTEM_PROMPT
