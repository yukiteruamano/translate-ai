"""Motor NLLB-200 sobre CTranslate2 (int8, CPU) con tokenización SentencePiece."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Sequence
from threading import Lock
from typing import Protocol

import ctranslate2
import sentencepiece as spm

from nllb_api.config import Settings
from nllb_api.constants import SPM_FILE
from nllb_api.cpu import available_cpus
from nllb_api.languages import Language

_EOS = "</s>"
_MAX_BATCH = 16
# ~2 M caracteres ≈ 8 MB de texto: unas 2 000 frases de 400 caracteres con su traducción.
_CACHE_MAX_CHARS = 2_000_000


class Engine(Protocol):
    def translate_sentences(
        self, sentences: Sequence[str], source: Language, target: Language
    ) -> list[str]: ...


class _LruCache:
    """LRU acotada por número de entradas y por caracteres (frase + traducción).

    El tope de caracteres evita que unas pocas frases enormes ocupen la memoria que
    `capacity` da por repartida entre frases normales.
    """

    def __init__(self, capacity: int, max_chars: int = _CACHE_MAX_CHARS) -> None:
        self._capacity = capacity
        self._max_chars = max_chars
        self._chars = 0
        self._items: OrderedDict[tuple[str, str, str], str] = OrderedDict()
        self._lock = Lock()

    def get(self, key: tuple[str, str, str]) -> str | None:
        with self._lock:
            if key not in self._items:
                return None
            self._items.move_to_end(key)
            return self._items[key]

    def put(self, key: tuple[str, str, str], value: str) -> None:
        cost = len(key[0]) + len(value)
        if self._capacity == 0 or cost > self._max_chars:
            return
        with self._lock:
            previous = self._items.get(key)
            if previous is not None:
                self._chars -= len(key[0]) + len(previous)
            self._items[key] = value
            self._items.move_to_end(key)
            self._chars += cost
            while len(self._items) > self._capacity or self._chars > self._max_chars:
                (sentence, _, _), evicted = self._items.popitem(last=False)
                self._chars -= len(sentence) + len(evicted)


class NllbEngine:
    """Seguro entre hilos: SentencePiece y `Translator` admiten llamadas concurrentes."""

    def __init__(self, settings: Settings) -> None:
        spm_path = settings.model_dir / SPM_FILE
        if not spm_path.is_file():
            raise FileNotFoundError(
                f"Modelo no encontrado en {settings.model_dir} (falta {SPM_FILE}). "
                "Ejecuta `python -m nllb_api.convert`."
            )
        self._sp = spm.SentencePieceProcessor(model_file=str(spm_path))
        self._translator = ctranslate2.Translator(
            str(settings.model_dir),
            device="cpu",
            compute_type=settings.compute_type,
            intra_threads=settings.intra_threads or available_cpus(),
            inter_threads=settings.inter_threads,
        )
        self._beam_size = settings.beam_size
        self._max_decoding_length = settings.max_decoding_length
        self._cache = _LruCache(settings.cache_size)

    def translate_sentences(
        self, sentences: Sequence[str], source: Language, target: Language
    ) -> list[str]:
        results: dict[str, str] = {}
        missing: list[str] = []
        for sentence in dict.fromkeys(sentences):
            cached = self._cache.get((sentence, source.code, target.code))
            if cached is None:
                missing.append(sentence)
            else:
                results[sentence] = cached
        if missing:
            for sentence, translation in zip(
                missing, self._translate(missing, source, target), strict=True
            ):
                results[sentence] = translation
                self._cache.put((sentence, source.code, target.code), translation)
        return [results[sentence] for sentence in sentences]

    def _translate(self, sentences: list[str], source: Language, target: Language) -> list[str]:
        batch = [[source.flores, *self._sp.encode(s, out_type=str), _EOS] for s in sentences]
        # Una traducción rara vez supera el doble de tokens; acota los bucles degenerados.
        limit = min(self._max_decoding_length, max(len(tokens) for tokens in batch) * 2 + 16)
        results = self._translator.translate_batch(
            batch,
            target_prefix=[[target.flores]] * len(batch),
            beam_size=self._beam_size,
            max_decoding_length=limit,
            max_batch_size=_MAX_BATCH,
        )
        # hypotheses[0][0] es el token de idioma destino.
        return [str(self._sp.decode_pieces(r.hypotheses[0][1:])) for r in results]
