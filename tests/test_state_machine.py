"""Tests for bot.state_machine — the deterministic transition logic."""

import pytest

from bot.state_machine import (
    Event,
    SessionStep,
    TransitionError,
    can_apply,
    is_confirm_word,
    is_terminal,
    next_step,
)


# ----------------------------------------------------------------- happy path

def test_full_vacancy_flow():
    """waiting_input -> waiting_boolean_confirm -> running -> done."""
    step = SessionStep.WAITING_INPUT
    step = next_step(step, Event.INPUT_RECEIVED)
    assert step == SessionStep.WAITING_BOOLEAN_CONFIRM
    step = next_step(step, Event.BOOLEAN_CONFIRMED)
    assert step == SessionStep.RUNNING
    step = next_step(step, Event.PIPELINE_DONE)
    assert step == SessionStep.DONE


def test_edited_boolean_also_goes_to_running():
    step = next_step(
        SessionStep.WAITING_BOOLEAN_CONFIRM, Event.BOOLEAN_EDITED
    )
    assert step == SessionStep.RUNNING


def test_pipeline_failure_goes_to_error():
    step = next_step(SessionStep.RUNNING, Event.PIPELINE_FAILED)
    assert step == SessionStep.ERROR


# --------------------------------------------------------------------- cancel

@pytest.mark.parametrize("step", [
    SessionStep.WAITING_INPUT,
    SessionStep.WAITING_BOOLEAN_CONFIRM,
    SessionStep.RUNNING,
])
def test_cancel_from_any_active_step(step):
    assert next_step(step, Event.CANCEL) == SessionStep.CANCELLED


# ---------------------------------------------------------------- bad events

def test_invalid_event_raises():
    with pytest.raises(TransitionError):
        next_step(SessionStep.WAITING_INPUT, Event.BOOLEAN_CONFIRMED)


def test_no_transition_from_terminal_steps():
    for step in (SessionStep.DONE, SessionStep.ERROR, SessionStep.CANCELLED):
        with pytest.raises(TransitionError):
            next_step(step, Event.CANCEL)


def test_can_apply():
    assert can_apply(SessionStep.WAITING_INPUT, Event.INPUT_RECEIVED) is True
    assert can_apply(SessionStep.WAITING_INPUT, Event.PIPELINE_DONE) is False


# -------------------------------------------------------------- helper checks

def test_is_terminal():
    assert is_terminal(SessionStep.DONE) is True
    assert is_terminal(SessionStep.ERROR) is True
    assert is_terminal(SessionStep.CANCELLED) is True
    assert is_terminal(SessionStep.RUNNING) is False
    assert is_terminal(SessionStep.WAITING_INPUT) is False


@pytest.mark.parametrize("word", ["ок", "ОК", "ok", "Ok", "да", "go", "GO",
                                  "approve", "yes", " ок ", "👍"])
def test_confirm_words_recognized(word):
    assert is_confirm_word(word) is True


@pytest.mark.parametrize("word", ["окей", "no", "нет", "Python AND Java", ""])
def test_non_confirm_words_rejected(word):
    assert is_confirm_word(word) is False


def test_no_waiting_brief_state():
    """Brief comes with the input — there is no separate WAITING_BRIEF step."""
    assert not any(s.value == "waiting_brief" for s in SessionStep)


def test_step_values_match_db_check_constraint():
    """SessionStep values must match the sessions.step CHECK in schema.sql."""
    assert {s.value for s in SessionStep} == {
        "waiting_input", "waiting_boolean_confirm", "running",
        "done", "error", "cancelled",
    }
