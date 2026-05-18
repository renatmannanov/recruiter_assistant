"""Session state machine.

The bot's whole flow is deterministic — no LLM on message routing.
This module defines the session steps and the pure transition logic:
given the current step and an event, what is the next step.

It does NOT touch Telegram or the DB. handlers.py wires events from
Telegram to these transitions and persists the result via db.client.
"""

from enum import Enum


class SessionStep(str, Enum):
    """Steps a session walks through. Values match the DB CHECK constraint."""

    WAITING_INPUT = "waiting_input"                      # awaiting JD/CV text or file(s)
    WAITING_BOOLEAN_CONFIRM = "waiting_boolean_confirm"  # boolean shown, awaiting 'ок' or an edit
    RUNNING = "running"                                  # pipeline executing in the background
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


# Steps from which a session can no longer advance.
TERMINAL_STEPS = frozenset({
    SessionStep.DONE, SessionStep.ERROR, SessionStep.CANCELLED,
})

# Words that confirm the generated boolean as-is (case-insensitive).
CONFIRM_WORDS = frozenset({"ок", "ok", "да", "go", "approve", "yes", "👍"})


class Event(str, Enum):
    """Things that can happen to a session."""

    INPUT_RECEIVED = "input_received"        # user sent JD/CV (+ optional brief)
    BOOLEAN_CONFIRMED = "boolean_confirmed"  # user approved the boolean
    BOOLEAN_EDITED = "boolean_edited"        # user sent a corrected boolean
    PIPELINE_DONE = "pipeline_done"
    PIPELINE_FAILED = "pipeline_failed"
    CANCEL = "cancel"


class TransitionError(Exception):
    """Raised when an event is not valid for the current step."""


# step -> {event: next_step}
_TRANSITIONS: dict[SessionStep, dict[Event, SessionStep]] = {
    SessionStep.WAITING_INPUT: {
        Event.INPUT_RECEIVED: SessionStep.WAITING_BOOLEAN_CONFIRM,
        Event.CANCEL: SessionStep.CANCELLED,
    },
    SessionStep.WAITING_BOOLEAN_CONFIRM: {
        Event.BOOLEAN_CONFIRMED: SessionStep.RUNNING,
        Event.BOOLEAN_EDITED: SessionStep.RUNNING,
        Event.CANCEL: SessionStep.CANCELLED,
    },
    SessionStep.RUNNING: {
        Event.PIPELINE_DONE: SessionStep.DONE,
        Event.PIPELINE_FAILED: SessionStep.ERROR,
        Event.CANCEL: SessionStep.CANCELLED,
    },
}


def is_terminal(step: SessionStep) -> bool:
    return SessionStep(step) in TERMINAL_STEPS


def is_confirm_word(text: str) -> bool:
    """True if the message is a plain confirmation of the boolean."""
    return text.strip().casefold() in CONFIRM_WORDS


def next_step(current: SessionStep, event: Event) -> SessionStep:
    """Return the step after applying `event` to `current`.

    Raises TransitionError if the event is invalid for this step — handlers
    turn that into a user-facing "не понял" reply.
    """
    current = SessionStep(current)
    event = Event(event)
    allowed = _TRANSITIONS.get(current, {})
    if event not in allowed:
        raise TransitionError(
            f"event {event.value!r} not allowed in step {current.value!r}"
        )
    return allowed[event]


def can_apply(current: SessionStep, event: Event) -> bool:
    """True if `event` is a valid transition from `current`."""
    return Event(event) in _TRANSITIONS.get(SessionStep(current), {})
