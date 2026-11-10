from __future__ import annotations

import time

import pytest
from tests.fakes import FakeEngine

from nllb_api.languages import SOURCE, resolve_target
from nllb_api.service import TranslationTimeoutError, stream_translation, translate_text

EN = resolve_target("en")


def _calls(engine: FakeEngine) -> list[list[str]]:
    return [sentences for sentences, _ in engine.calls]


def test_groups_sentences_into_chunks_up_to_the_limit() -> None:
    engine = FakeEngine()
    translate_text(engine, "Aaaa. Bbbb. Cccc. Dddd.", SOURCE, EN, 400, 10)
    assert _calls(engine) == [["Aaaa.", "Bbbb."], ["Cccc.", "Dddd."]]


def test_a_single_line_larger_than_the_limit_is_split_by_sentences() -> None:
    engine = FakeEngine()
    text = " ".join(f"Frase número {n}." for n in range(100))
    result = translate_text(engine, text, SOURCE, EN, 400, 200)
    assert len(engine.calls) > 1
    assert result == " ".join(f"[en] Frase número {n}." for n in range(100))


def test_separators_survive_chunk_boundaries() -> None:
    engine = FakeEngine()
    result = translate_text(engine, "Uno. Dos.\n\nTres.\n", SOURCE, EN, 400, 5)
    assert result == "[en] Uno. [en] Dos.\n\n[en] Tres.\n"


def test_whitespace_only_text_keeps_line_breaks_without_calling_the_engine() -> None:
    engine = FakeEngine()
    assert translate_text(engine, "  \n ", SOURCE, EN, 400, 100) == "\n"
    assert engine.calls == []


def test_is_lazy_so_a_disconnected_client_stops_further_chunks() -> None:
    engine = FakeEngine()
    pieces = stream_translation(engine, "Aaaa. Bbbb. Cccc.", SOURCE, EN, 400, 5)
    assert next(pieces) == "[en] Aaaa."
    assert len(engine.calls) == 1
    pieces.close()
    assert len(engine.calls) == 1


def test_raises_when_the_deadline_has_passed_before_starting_a_chunk() -> None:
    engine = FakeEngine()
    with pytest.raises(TranslationTimeoutError):
        translate_text(engine, "Uno.", SOURCE, EN, 400, 100, deadline=time.monotonic() - 1)
    assert engine.calls == []
