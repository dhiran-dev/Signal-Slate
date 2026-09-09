"""Public developer regressions; these are not the private held-out accuracy set."""

from unittest.mock import MagicMock

import pytest
from google.genai import Client
from signal_slate.agent.live_adk import SignalSlateAdkAgent
from signal_slate.agent.safety import ConstraintValidationError, validate_interpretation
from signal_slate.domain.models import Constraint, ConstraintInterpretation, ShotContext


def interpretation(**changes):
    payload = dict(
        constraint_id="c1",
        kind="CHANNEL_EXCLUSION",
        target_mic="mic_1",
        parameters={"excluded_channel": 11},
        source_text="Exclude channel 11",
        exact_source_span="channel 11",
        confirmed=False,
    )
    payload.update(changes)
    return ConstraintInterpretation(
        status="SUPPORTED", constraints=[Constraint(**payload)], rationale="Restriction"
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"confirmed": True},
        {"source_text": "different"},
        {"exact_source_span": "invented"},
        {"exact_source_span": ""},
        {"target_mic": "mic_unknown"},
        {"kind": "CUSTOM"},
        {"parameters": {"excluded_channel": True}},
        {"parameters": {"excluded_channel": 999}},
        {"parameters": {"excluded_channel": 11, "approved": True}},
        {"kind": "RIG_LOCK", "parameters": {"locked": True}},
        {"kind": "ANTENNA_LOCK", "parameters": {"locked_antenna": "X"}},
        {"kind": "BOOM_EXCLUSION", "parameters": {"enabled": False}},
    ],
)
def test_model_output_cannot_cross_confirmation_boundary(changes):
    with pytest.raises(ConstraintValidationError):
        validate_interpretation(interpretation(**changes), "Exclude channel 11", ShotContext())


def test_supported_exact_source_passes_without_human_authority():
    result = validate_interpretation(interpretation(), "Exclude channel 11", ShotContext())
    assert not result.constraints[0].confirmed


@pytest.mark.parametrize("status", ["UNSUPPORTED", "AMBIGUOUS", "CONTRADICTORY"])
def test_refusal_never_smuggles_confirmable_constraints(status):
    result = interpretation()
    result.status = status
    with pytest.raises(ConstraintValidationError):
        validate_interpretation(result, "Exclude channel 11", ShotContext())


@pytest.mark.asyncio
async def test_empty_input_is_zero_model_fast_path():
    agent = SignalSlateAdkAgent(db_session_factory=MagicMock(), genai_client=MagicMock(spec=Client))
    result = await agent.interpret_constraint("not-even-a-workflow", "   ", ShotContext())
    assert result.status == "AMBIGUOUS"
    agent.db_session_factory.assert_not_called()


@pytest.mark.asyncio
async def test_oversized_input_is_rejected_before_model():
    agent = SignalSlateAdkAgent(db_session_factory=MagicMock(), genai_client=MagicMock(spec=Client))
    with pytest.raises(ValueError, match="2000"):
        await agent.interpret_constraint("not-even-a-workflow", "x" * 2001, ShotContext())
    agent.db_session_factory.assert_not_called()


def test_conflicting_antenna_locks_reject_even_across_targets():
    result = interpretation(kind="ANTENNA_LOCK", parameters={"locked_antenna": "A"})
    other = result.constraints[0].model_copy(
        update={"constraint_id": "c2", "target_mic": "mic_2", "parameters": {"locked_antenna": "B"}}
    )
    result.constraints.append(other)
    with pytest.raises(ConstraintValidationError, match="Conflicting"):
        validate_interpretation(result, "Exclude channel 11", ShotContext())
