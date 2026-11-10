"""`NllbEngine` con CTranslate2 y SentencePiece sustituidos: corre sin el modelo real."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from nllb_api import engine as engine_module
from nllb_api.config import Settings
from nllb_api.constants import SPM_FILE
from nllb_api.engine import NllbEngine, _LruCache
from nllb_api.languages import SOURCE, TARGETS

ENGLISH = TARGETS[0]


class FakeSentencePiece:
    def __init__(self, model_file: str) -> None:
        self.model_file = model_file

    def encode(self, text: str, out_type: type = str) -> list[str]:
        return text.split()

    def decode_pieces(self, pieces: list[str]) -> str:
        return " ".join(pieces)


@dataclass
class FakeResult:
    hypotheses: list[list[str]]


class FakeTranslator:
    instances: list[FakeTranslator] = []

    def __init__(self, path: str, **kwargs: Any) -> None:
        self.path = path
        self.kwargs = kwargs
        self.batches: list[list[list[str]]] = []
        self.options: list[dict[str, Any]] = []
        FakeTranslator.instances.append(self)

    def translate_batch(
        self, batch: list[list[str]], target_prefix: list[list[str]], **options: Any
    ) -> list[FakeResult]:
        self.batches.append(batch)
        self.options.append({"target_prefix": target_prefix, **options})
        return [
            FakeResult([[prefix[0], *(token.upper() for token in tokens[1:-1])]])
            for tokens, prefix in zip(batch, target_prefix, strict=True)
        ]


@pytest.fixture(autouse=True)
def fake_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeTranslator.instances.clear()
    monkeypatch.setattr(engine_module.spm, "SentencePieceProcessor", FakeSentencePiece)
    monkeypatch.setattr(engine_module.ctranslate2, "Translator", FakeTranslator)
    monkeypatch.setattr(engine_module, "available_cpus", lambda: 3)


def make_settings(tmp_path: Path, **env: str) -> Settings:
    (tmp_path / SPM_FILE).write_bytes(b"")
    return Settings.from_env({"MODEL_DIR": str(tmp_path), **env})


def test_missing_model_fails_fast_with_a_hint(tmp_path: Path) -> None:
    settings = Settings.from_env({"MODEL_DIR": str(tmp_path / "vacío")})
    with pytest.raises(FileNotFoundError, match="nllb_api.convert"):
        NllbEngine(settings)


def test_wraps_each_sentence_with_language_tokens_and_strips_the_target_prefix(
    tmp_path: Path,
) -> None:
    engine = NllbEngine(make_settings(tmp_path))
    assert engine.translate_sentences(["hola mundo"], SOURCE, ENGLISH) == ["HOLA MUNDO"]
    translator = FakeTranslator.instances[0]
    assert translator.batches == [[["spa_Latn", "hola", "mundo", "</s>"]]]
    assert translator.options[0]["target_prefix"] == [["eng_Latn"]]
    assert translator.options[0]["beam_size"] == 4


def test_deduplicates_and_caches_sentences(tmp_path: Path) -> None:
    engine = NllbEngine(make_settings(tmp_path))
    assert engine.translate_sentences(["uno", "dos", "uno"], SOURCE, ENGLISH) == [
        "UNO",
        "DOS",
        "UNO",
    ]
    translator = FakeTranslator.instances[0]
    assert [row[1] for row in translator.batches[0]] == ["uno", "dos"]
    engine.translate_sentences(["dos", "uno"], SOURCE, ENGLISH)
    assert len(translator.batches) == 1
    engine.translate_sentences(["uno"], SOURCE, TARGETS[1])
    assert len(translator.batches) == 2  # otro idioma destino: no sirve la caché


def test_cache_can_be_disabled(tmp_path: Path) -> None:
    engine = NllbEngine(make_settings(tmp_path, CACHE_SIZE="0"))
    engine.translate_sentences(["uno"], SOURCE, ENGLISH)
    engine.translate_sentences(["uno"], SOURCE, ENGLISH)
    assert len(FakeTranslator.instances[0].batches) == 2


def test_threads_follow_the_container_quota_unless_configured(tmp_path: Path) -> None:
    NllbEngine(make_settings(tmp_path))
    assert FakeTranslator.instances[0].kwargs["intra_threads"] == 3
    NllbEngine(make_settings(tmp_path, CT2_INTRA_THREADS="2"))
    assert FakeTranslator.instances[1].kwargs["intra_threads"] == 2


def test_decoding_length_is_bounded_by_the_input(tmp_path: Path) -> None:
    engine = NllbEngine(make_settings(tmp_path, MAX_DECODING_LENGTH="64"))
    engine.translate_sentences(["a b c"], SOURCE, ENGLISH)  # 5 tokens → 5*2+16 = 26
    engine.translate_sentences([" ".join(["x"] * 100)], SOURCE, ENGLISH)  # tope de 64
    limits = [o["max_decoding_length"] for o in FakeTranslator.instances[0].options]
    assert limits == [26, 64]


def test_cache_evicts_the_least_recently_used_entry() -> None:
    cache = _LruCache(2)
    cache.put(("a", "es", "en"), "A")
    cache.put(("b", "es", "en"), "B")
    assert cache.get(("a", "es", "en")) == "A"
    cache.put(("c", "es", "en"), "C")
    assert cache.get(("b", "es", "en")) is None
    assert cache.get(("a", "es", "en")) == "A"


def test_cache_is_bounded_by_characters_too() -> None:
    cache = _LruCache(100, max_chars=10)
    cache.put(("aaaa", "es", "en"), "AAAA")
    cache.put(("bbbb", "es", "en"), "BBBB")  # 16 > 10: expulsa la más antigua
    assert cache.get(("aaaa", "es", "en")) is None
    assert cache.get(("bbbb", "es", "en")) == "BBBB"
    cache.put(("x" * 50, "es", "en"), "X")  # una sola entrada que no cabe: no se guarda
    assert cache.get(("x" * 50, "es", "en")) is None
    assert cache.get(("bbbb", "es", "en")) == "BBBB"


def test_replacing_an_entry_does_not_inflate_the_character_count() -> None:
    cache = _LruCache(10, max_chars=10)
    for _ in range(20):
        cache.put(("abc", "es", "en"), "ABC")
    cache.put(("def", "es", "en"), "DEF")  # 12 > 10: expulsa solo la primera
    assert cache.get(("abc", "es", "en")) is None
    assert cache.get(("def", "es", "en")) == "DEF"
