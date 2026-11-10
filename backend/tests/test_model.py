"""Integración con el modelo real. Se omite si MODEL_DIR no contiene el modelo convertido."""

from __future__ import annotations

import pytest

from nllb_api.config import Settings
from nllb_api.constants import SPM_FILE
from nllb_api.engine import NllbEngine
from nllb_api.languages import SOURCE, resolve_target
from nllb_api.service import translate_text

pytestmark = pytest.mark.model


@pytest.fixture(scope="module")
def engine() -> NllbEngine:
    settings = Settings.from_env()
    if not (settings.model_dir / SPM_FILE).is_file():
        pytest.skip(f"sin modelo en {settings.model_dir}")
    return NllbEngine(settings)


@pytest.mark.parametrize(
    ("target", "expected"),
    [("en", "buy"), ("de", "kaufen"), ("fr", "acheter"), ("it", "acquistare"), ("pt", "comprar")],
)
def test_translates_to_every_target(engine: NllbEngine, target: str, expected: str) -> None:
    text = "¿Cómo puedo comprar bitcoin de forma segura?"
    result = translate_text(engine, text, SOURCE, resolve_target(target), 400, 10_000)
    assert expected in result.lower()
    assert "bitcoin" in result.lower()


def test_keeps_lines_and_uses_cache(engine: NllbEngine) -> None:
    target = resolve_target("en")
    text = "Hola.\n\nAdiós."
    first = translate_text(engine, text, SOURCE, target, 400, 10_000)
    assert first.count("\n") == 2
    assert translate_text(engine, text, SOURCE, target, 400, 10_000) == first
