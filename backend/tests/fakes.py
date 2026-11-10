"""Motores de prueba que sustituyen al modelo real."""

from __future__ import annotations

from collections.abc import Sequence

from nllb_api.languages import Language


class FakeEngine:
    """Traduce `frase` → `[<destino>] frase` y registra las llamadas."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    def translate_sentences(
        self, sentences: Sequence[str], source: Language, target: Language
    ) -> list[str]:
        self.calls.append((list(sentences), target.code))
        return [f"[{target.code}] {s}" for s in sentences]


class BrokenEngine:
    def translate_sentences(
        self, sentences: Sequence[str], source: Language, target: Language
    ) -> list[str]:
        raise RuntimeError("detalle interno que no debe filtrarse")
