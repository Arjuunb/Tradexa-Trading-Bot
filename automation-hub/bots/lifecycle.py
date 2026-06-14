"""Bot lifecycle state machine.

Centralizes the legal transitions so the manager/UI can't push a bot into an
inconsistent state. Phase 1 supports the create -> run/paper -> pause -> stop
flow plus the emergency stop.
"""
from __future__ import annotations

from database.models import BotState

# Allowed transitions.
_TRANSITIONS: dict[BotState, set[BotState]] = {
    BotState.CREATED: {BotState.RUNNING, BotState.PAPER, BotState.ERROR},
    BotState.PAPER: {BotState.PAUSED, BotState.STOPPED, BotState.RUNNING, BotState.ERROR},
    BotState.RUNNING: {BotState.PAUSED, BotState.STOPPED, BotState.ERROR},
    BotState.PAUSED: {BotState.RUNNING, BotState.PAPER, BotState.STOPPED, BotState.ERROR},
    BotState.STOPPED: {BotState.RUNNING, BotState.PAPER},
    BotState.ERROR: {BotState.STOPPED, BotState.PAPER, BotState.RUNNING},
}


class IllegalTransition(Exception):
    pass


def can_transition(src: BotState, dst: BotState) -> bool:
    return dst in _TRANSITIONS.get(src, set())


def assert_transition(src: BotState, dst: BotState) -> None:
    if not can_transition(src, dst):
        raise IllegalTransition(f"cannot move bot from {src.value} to {dst.value}")
