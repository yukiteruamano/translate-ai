from __future__ import annotations

import pytest

from nllb_api.security import ConcurrencyGate, ServerBusyError


def test_gate_rejects_beyond_the_limit_and_frees_on_release() -> None:
    gate = ConcurrencyGate(2)
    first, _second = gate.acquire(), gate.acquire()
    with pytest.raises(ServerBusyError):
        gate.acquire()
    first.release()
    assert gate.active == 1
    gate.acquire()


def test_release_is_idempotent() -> None:
    gate = ConcurrencyGate(1)
    slot = gate.acquire()
    slot.release()
    slot.release()
    assert gate.active == 0
    gate.acquire()
    with pytest.raises(ServerBusyError):
        gate.acquire()


def test_slot_works_as_a_context_manager() -> None:
    gate = ConcurrencyGate(1)
    with gate.acquire():
        assert gate.active == 1
    assert gate.active == 0


def test_zero_means_unlimited() -> None:
    gate = ConcurrencyGate(0)
    for _ in range(100):
        gate.acquire()
    assert gate.active == 100
