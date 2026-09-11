"""Public Agent event contract tests."""

from app.agent.contracts.events import AgentEvent
from app.qa.llm import generate_answer, render_generated_markdown


def test_tool_lifecycle_has_stable_step_id_and_distinguishes_repeated_calls() -> None:
    started = AgentEvent(
        event_id="evt-1", run_id="run-1", seq=1, timestamp="2026-09-11T00:00:00Z",
        type="step.started", kind="tool", step_id="search-1",
        display_name="企业知识检索", description="查询产品资料", status="RUNNING",
    )
    completed = started.model_copy(update={
        "event_id": "evt-2", "seq": 2, "type": "step.completed",
        "status": "SUCCEEDED", "duration_ms": 1320,
    })
    repeated = started.model_copy(update={"event_id": "evt-3", "seq": 3, "step_id": "search-2"})

    assert completed.step_id == "search-1"
    assert completed.duration_ms == 1320
    assert repeated.step_id != completed.step_id


def test_phase_event_is_not_a_tool_step() -> None:
    event = AgentEvent(
        event_id="evt-phase", run_id="run-1", seq=4, timestamp="2026-09-11T00:00:01Z",
        type="phase.started", kind="reasoning", phase="analyzing",
        display_name="分析问题", status="RUNNING",
    )

    assert event.phase == "analyzing"
    assert event.step_id is None


def test_legacy_generation_stream_emits_deltas_and_canonical_markdown() -> None:
    payload = (
        '{"answer_type":"ANSWER","summary":"先给结论。",'
        '"blocks":[{"type":"paragraph","content":"依据资料说明。",'
        '"citation_ids":["E1"]}],"follow_up_suggestions":[]}'
    )
    deltas: list[str] = []
    generated = generate_answer(
        None,
        question="问题",
        evidence_text="[E1] 资料",
        stream_fn=lambda _messages: (payload[index:index + 5] for index in range(0, len(payload), 5)),
        on_delta=deltas.append,
        chat_fn=lambda _messages: "不应走非流式路径",
    )

    assert "".join(deltas) == generated.summary
    assert render_generated_markdown(generated, citation_id_to_no={"E1": 1}) == (
        "先给结论。\n\n依据资料说明。 [1]"
    )
