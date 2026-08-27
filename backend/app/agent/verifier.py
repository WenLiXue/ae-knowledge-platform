"""Deterministic progress and completion verification."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts.plan import AgentPlan


@dataclass(frozen=True)
class Verification:
    complete: bool
    needs_replan: bool = False
    needs_input: bool = False
    reason: str = ""
    missing: tuple[str, ...] = ()


def verify_plan(plan: AgentPlan, observations: list[dict]) -> Verification:
    """Verify execution state without asking the model to self-certify success."""
    failed = [step for step in plan.steps if step.status == "FAILED"]
    if failed:
        retryable = any(bool(item.get("retryable")) for item in observations if item.get("step_id") in {s.id for s in failed})
        return Verification(
            complete=False,
            needs_replan=retryable,
            reason="RETRYABLE_STEP_FAILED" if retryable else "STEP_FAILED",
            missing=tuple(step.id for step in failed),
        )
    pending = [step for step in plan.steps if step.status not in ("SUCCEEDED", "SKIPPED")]
    if pending:
        return Verification(complete=False, reason="STEPS_PENDING", missing=tuple(step.id for step in pending))
    missing_criteria = _missing_criteria(plan, observations)
    if missing_criteria:
        return Verification(complete=False, needs_replan=True, reason="COMPLETION_CRITERIA_MISSING", missing=tuple(missing_criteria))
    return Verification(complete=True, reason="COMPLETE")


def _missing_criteria(plan: AgentPlan, observations: list[dict]) -> list[str]:
    missing: list[str] = []
    for criterion in plan.completion_criteria:
        if not criterion.required:
            continue
        params = criterion.params
        if criterion.type == "EVIDENCE_BOUND":
            if not any(item.get("evidence_refs") for item in observations):
                missing.append("EVIDENCE_BOUND")
        elif criterion.type == "ACTION_VERIFIED":
            if not any(item.get("action_verified") is True for item in observations):
                missing.append("ACTION_VERIFIED")
        elif criterion.type == "SET_COVERAGE":
            required = set(params.get("required_ids") or [])
            observed = {str(value) for item in observations for value in (item.get("covered_ids") or [])}
            if required and not required.issubset(observed):
                missing.append("SET_COVERAGE")
        elif criterion.type == "REQUIRED_FIELDS":
            fields = set(params.get("fields") or [])
            if fields and not any(fields.issubset(set(item.get("fields") or [])) for item in observations):
                missing.append("REQUIRED_FIELDS")
    return missing
