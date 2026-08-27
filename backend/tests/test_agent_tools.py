from datetime import datetime, timezone

from pydantic import BaseModel

from app.agent.contracts.tool import ToolDefinition, ToolResultEnvelope, ToolCallProposal
from app.agent.contracts.plan import AgentPlan, PlanStep
from app.agent.planner import PlannerLimits, ready_steps, validate_plan
from app.agent.tools import ToolContext, ToolExecutor, ToolPolicy, ToolRegistry


class Input(BaseModel):
    value: str


class Output(BaseModel):
    value: str


class ReadTool:
    input_model = Input
    output_model = Output
    definition = ToolDefinition(
        name="test.read",
        version="1.0",
        description="test read tool",
        input_schema=Input.model_json_schema(),
        output_schema=Output.model_json_schema(),
        risk="READ_ONLY",
        side_effect=False,
        requires_confirmation=False,
        idempotency="NOT_APPLICABLE",
        required_permissions=["test:read"],
    )

    def execute(self, args, context):
        now = datetime.now(timezone.utc)
        return ToolResultEnvelope(
            call_id=context.metadata["call_id"],
            tool_name=self.definition.name,
            tool_version=self.definition.version,
            status="SUCCEEDED",
            data={"value": args.value},
            summary="ok",
            started_at=now,
            completed_at=now,
        )


def test_registry_executes_only_registered_tools() -> None:
    registry = ToolRegistry()
    registry.register(ReadTool())
    executor = ToolExecutor(registry)
    result = executor.execute(
        ToolCallProposal(call_id="call-1", tool_name="test.read", arguments={"value": "ok"}),
        ToolContext(user_id="user-1", permissions=frozenset({"test:read"})),
    )
    assert result.status == "SUCCEEDED"
    assert result.call_id == "call-1"
    assert result.data == {"value": "ok"}

    unknown = executor.execute(
        ToolCallProposal(call_id="call-2", tool_name="test.unknown"),
        ToolContext(user_id="user-1", permissions=frozenset({"test:read"})),
    )
    assert unknown.error_code == "TOOL_NOT_REGISTERED"


def test_policy_denies_missing_permission_and_invalid_input() -> None:
    registry = ToolRegistry()
    registry.register(ReadTool())
    executor = ToolExecutor(registry)

    denied = executor.execute(
        ToolCallProposal(tool_name="test.read", arguments={"value": "ok"}),
        ToolContext(user_id="user-1"),
    )
    assert denied.error_code == "TOOL_PERMISSION_DENIED"

    invalid = executor.execute(
        ToolCallProposal(tool_name="test.read", arguments={"unexpected": True}),
        ToolContext(user_id="user-1", permissions=frozenset({"test:read"})),
    )
    assert invalid.error_code == "TOOL_INPUT_INVALID"


def test_plan_validation_enforces_tools_permissions_and_dependencies() -> None:
    registry = ToolRegistry()
    registry.register(ReadTool())
    plan = AgentPlan(
        id="plan-1",
        goal="读取数据",
        steps=[
            PlanStep(
                id="read",
                title="读取",
                capability="test.read",
                expected_output="一条结果",
            )
        ],
    )
    validate_plan(
        plan,
        registry,
        permissions=frozenset({"test:read"}),
        limits=PlannerLimits(max_steps=1),
    )
    assert ready_steps(plan) == ["read"]

    bad = plan.model_copy(update={"steps": [plan.steps[0].model_copy(update={"capability": "test.missing"})]})
    try:
        validate_plan(bad, registry, permissions=frozenset({"test:read"}))
    except Exception as exc:
        assert getattr(exc, "code", None) == "TOOL_NOT_REGISTERED"
    else:
        raise AssertionError("unknown capability must be rejected")
