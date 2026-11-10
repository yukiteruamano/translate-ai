"""Idiomas soportados: origen fijo en español y cinco destinos."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str  # ISO 639-1: el identificador público de la API
    flores: str  # código FLORES-200 que espera NLLB
    name: str


SOURCE = Language("es", "spa_Latn", "Español")
TARGETS = (
    Language("en", "eng_Latn", "Inglés"),
    Language("pt", "por_Latn", "Portugués"),
    Language("de", "deu_Latn", "Alemán"),
    Language("fr", "fra_Latn", "Francés"),
    Language("it", "ita_Latn", "Italiano"),
)


# Cuánto del valor rechazado se devuelve en el mensaje de error.
_ECHO_CHARS = 32


class UnsupportedLanguageError(ValueError):
    """El código recibido no es un idioma de origen/destino admitido."""


def _resolve(value: str, allowed: tuple[Language, ...], role: str) -> Language:
    wanted = value.strip().lower()
    for language in allowed:
        if wanted in (language.code, language.flores.lower()):
            return language
    supported = ", ".join(language.code for language in allowed)
    raise UnsupportedLanguageError(
        f"Idioma de {role} no soportado: {value[:_ECHO_CHARS]!r}. Admitidos: {supported}."
    )


def resolve_source(value: str) -> Language:
    return _resolve(value, (SOURCE,), "origen")


def resolve_target(value: str) -> Language:
    return _resolve(value, TARGETS, "destino")
