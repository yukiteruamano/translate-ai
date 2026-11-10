"""Traducción de textos multilínea: conserva saltos de línea y traduce por trozos."""

from __future__ import annotations

import time
from collections.abc import Iterator

from nllb_api.engine import Engine
from nllb_api.languages import Language
from nllb_api.segmentation import split_sentences


class TranslationTimeoutError(Exception):
    """Se agotó el tiempo máximo de la petición entre dos trozos."""


# (separador previo, frase): el separador es "\n" por línea, " " entre frases o "".
_Unit = tuple[str, str]


def _units(text: str, max_sentence_chars: int) -> tuple[list[_Unit], str]:
    """Frases del texto con el separador que las precede, y los saltos finales sin frase."""
    units: list[_Unit] = []
    pending = ""
    for index, line in enumerate(text.replace("\r\n", "\n").split("\n")):
        if index:
            pending += "\n"
        for position, sentence in enumerate(split_sentences(line, max_sentence_chars)):
            units.append((pending if position == 0 else " ", sentence))
            if position == 0:
                pending = ""
    return units, pending


def _chunks(units: list[_Unit], max_chunk_chars: int) -> Iterator[list[_Unit]]:
    """Agrupa frases consecutivas hasta `max_chunk_chars`; una frase nunca se parte."""
    chunk: list[_Unit] = []
    size = 0
    for unit in units:
        length = len(unit[1])
        if chunk and size + length > max_chunk_chars:
            yield chunk
            chunk, size = [], 0
        chunk.append(unit)
        size += length
    if chunk:
        yield chunk


def stream_translation(
    engine: Engine,
    text: str,
    source: Language,
    target: Language,
    max_sentence_chars: int,
    max_chunk_chars: int,
    *,
    deadline: float | None = None,
) -> Iterator[str]:
    """Emite cada trozo traducido en cuanto está listo.

    Es perezoso: si el consumidor deja de iterar (cliente desconectado), los trozos
    restantes no se traducen. Solo el trozo en curso se completa. `deadline` es un
    instante de `time.monotonic()`: si pasa antes de empezar un trozo, lanza
    `TranslationTimeoutError`.
    """
    units, tail = _units(text, max_sentence_chars)
    for chunk in _chunks(units, max_chunk_chars):
        if deadline is not None and time.monotonic() > deadline:
            raise TranslationTimeoutError
        translated = engine.translate_sentences([s for _, s in chunk], source, target)
        yield "".join(
            prefix + sentence for (prefix, _), sentence in zip(chunk, translated, strict=True)
        )
    if tail:
        yield tail


def translate_text(
    engine: Engine,
    text: str,
    source: Language,
    target: Language,
    max_sentence_chars: int,
    max_chunk_chars: int,
    *,
    deadline: float | None = None,
) -> str:
    return "".join(
        stream_translation(
            engine, text, source, target, max_sentence_chars, max_chunk_chars, deadline=deadline
        )
    )
