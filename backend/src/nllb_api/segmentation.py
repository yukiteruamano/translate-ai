"""Troceo de texto en frases.

NLLB se entrenó con frases sueltas: por encima de ~512 tokens la calidad cae y
aparecen repeticiones o truncados. Traducir frase a frase también permite agrupar
en lotes y cachear.
"""

from __future__ import annotations

import re

# Cierre de frase seguido de espacio: no parte "3.5" ni URLs.
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
# Marcador de lista ("1." / "2)") solo en su fragmento; iniciales y siglas con puntos
# ("S.A.", "EE.UU.").
_LIST_MARKER = re.compile(r"\d{1,3}[.)]")
_DOTTED_INITIALISM = re.compile(r"(?:[^\W\d_]{1,2}\.){2,}")
# Abreviaturas del español tras las que un punto no cierra la frase. Se omite "etc.", que
# sí suele cerrarla. Si una cierra frase de verdad, el fallo es una frase más larga: inocuo.
_ABBREVIATIONS = frozenset(
    {
        "sr.", "sra.", "srta.", "srs.", "sres.", "dr.", "dra.", "prof.", "profa.", "lic.",
        "ing.", "arq.", "ud.", "uds.", "vd.", "vds.", "ej.", "núm.", "pág.", "págs.", "cap.",
        "art.", "arts.", "aprox.", "vs.", "fig.", "tel.", "av.", "avda.", "ee.", "uu.",
    }
)  # fmt: skip


def _ends_open(fragment: str) -> bool:
    """El fragmento termina en un punto que no cierra la frase."""
    if _LIST_MARKER.fullmatch(fragment):
        return True
    last = fragment.rsplit(None, 1)[-1]
    return (
        last.lower() in _ABBREVIATIONS
        or (len(last) == 2 and last[0].isalpha() and last[1] == ".")
        or bool(_DOTTED_INITIALISM.fullmatch(last))
    )


def _merge_open_fragments(fragments: list[str]) -> list[str]:
    """Une cada fragmento que no cierra frase con el siguiente."""
    merged: list[str] = []
    carry = ""
    for fragment in fragments:
        current = f"{carry} {fragment}" if carry else fragment
        if _ends_open(current):
            carry = current
        else:
            merged.append(current)
            carry = ""
    if carry:
        merged.append(carry)
    return merged


def _wrap(sentence: str, max_chars: int) -> list[str]:
    """Parte una frase demasiado larga en palabras sin superar `max_chars`.

    Una palabra mayor que `max_chars` (URL, cadena sin espacios) se corta por caracteres:
    el encoder trunca en silencio lo que exceda su ventana.
    """
    chunks: list[str] = []
    current = ""
    for word in sentence.split():
        while len(word) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(word[:max_chars])
            word = word[max_chars:]
        candidate = f"{current} {word}" if current else word
        if len(candidate) > max_chars and current:
            chunks.append(current)
            current = word
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def split_sentences(line: str, max_chars: int) -> list[str]:
    """Frases de una línea, ninguna mayor que `max_chars`."""
    sentences: list[str] = []
    fragments = [f.strip() for f in _SENTENCE_END.split(line.strip()) if f.strip()]
    for sentence in _merge_open_fragments(fragments):
        if len(sentence) <= max_chars:
            sentences.append(sentence)
        else:
            sentences.extend(_wrap(sentence, max_chars))
    return sentences
