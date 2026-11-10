from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.fakes import FakeEngine

from nllb_api.config import Settings
from nllb_api.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings.from_env({"STATIC_DIR": str(tmp_path / "sin-ui"), "MAX_INPUT_CHARS": "200"})


@pytest.fixture
def engine() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
def client(settings: Settings, engine: FakeEngine) -> Iterator[TestClient]:
    with TestClient(create_app(settings, lambda _: engine)) as test_client:
        yield test_client
