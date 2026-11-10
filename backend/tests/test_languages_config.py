import pytest

from nllb_api.config import Settings
from nllb_api.languages import (
    UnsupportedLanguageError,
    resolve_source,
    resolve_target,
)


@pytest.mark.parametrize(
    ("value", "flores"),
    [("en", "eng_Latn"), ("PT", "por_Latn"), (" de ", "deu_Latn"), ("fra_Latn", "fra_Latn")],
)
def test_resolves_targets_by_iso_or_flores(value: str, flores: str) -> None:
    assert resolve_target(value).flores == flores


@pytest.mark.parametrize("value", ["es", "ja", "", "eng"])
def test_rejects_unsupported_targets(value: str) -> None:
    with pytest.raises(UnsupportedLanguageError):
        resolve_target(value)


def test_source_is_only_spanish() -> None:
    assert resolve_source("spa_Latn").code == "es"
    with pytest.raises(UnsupportedLanguageError):
        resolve_source("en")


def test_settings_defaults_and_validation() -> None:
    defaults = Settings.from_env({})
    assert defaults.beam_size == 4
    assert defaults.cors_origins == ()
    assert Settings.from_env({"CORS_ORIGINS": "https://a.com, https://b.com"}).cors_origins == (
        "https://a.com",
        "https://b.com",
    )
    with pytest.raises(ValueError, match="BEAM_SIZE"):
        Settings.from_env({"BEAM_SIZE": "cuatro"})
    with pytest.raises(ValueError, match="CT2_INTER_THREADS"):
        Settings.from_env({"CT2_INTER_THREADS": "0"})


def test_settings_limits_and_flags() -> None:
    defaults = Settings.from_env({})
    assert (defaults.max_input_chars, defaults.max_chunk_chars) == (50_000, 1_500)
    assert (defaults.max_concurrent_requests, defaults.request_timeout_seconds) == (8, 900)
    assert defaults.enable_docs is True
    assert Settings.from_env({"ENABLE_DOCS": "0"}).enable_docs is False
    assert Settings.from_env({"ENABLE_DOCS": " Off "}).enable_docs is False
    assert Settings.from_env({"MAX_CONCURRENT_REQUESTS": "0"}).max_concurrent_requests == 0
    with pytest.raises(ValueError, match="ENABLE_DOCS"):
        Settings.from_env({"ENABLE_DOCS": "quizás"})


def test_log_level_is_validated() -> None:
    assert Settings.from_env({}).log_level == "INFO"
    assert Settings.from_env({"LOG_LEVEL": " debug "}).log_level == "DEBUG"
    with pytest.raises(ValueError, match="LOG_LEVEL"):
        Settings.from_env({"LOG_LEVEL": "verbose"})


def test_rejected_language_echoes_only_a_short_prefix() -> None:
    with pytest.raises(UnsupportedLanguageError) as error:
        resolve_target("x" * 10_000)
    assert len(str(error.value)) < 200
