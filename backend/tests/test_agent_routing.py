from app.agent.policies import looks_like_knowledge_question


def test_general_programming_request_does_not_enter_enterprise_search() -> None:
    assert looks_like_knowledge_question("给我写一个 C 语言版本的接雨水") is False


def test_enterprise_hardware_question_still_enters_search() -> None:
    assert looks_like_knowledge_question("现在 AE 有哪些硬件型号，性能怎么样？") is True
