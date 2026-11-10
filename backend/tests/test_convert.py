from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from nllb_api import convert
from nllb_api.constants import SPM_FILE


@dataclass
class Completed:
    returncode: int


@pytest.fixture
def calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    recorded: list[list[str]] = []

    def fake_run(command: list[str], check: bool) -> Completed:
        assert check is False
        recorded.append(command)
        return Completed(0)

    monkeypatch.setattr(convert, "MODEL_DIR", tmp_path / "models" / "m")
    monkeypatch.setattr(convert, "_download_snapshot", lambda: "/snapshot")
    monkeypatch.setattr(convert.subprocess, "run", fake_run)
    return recorded


def test_converts_from_the_pinned_local_snapshot(calls: list[list[str]]) -> None:
    assert convert.main() == 0
    command = calls[0]
    assert command[command.index("--model") + 1] == "/snapshot"
    assert command[command.index("--output_dir") + 1] == str(convert.MODEL_DIR)
    assert command[command.index("--quantization") + 1] == convert.QUANTIZATION
    assert command[command.index("--copy_files") + 1] == SPM_FILE
    assert "--low_cpu_mem_usage" in command
    assert convert.MODEL_DIR.parent.is_dir()


def test_skips_when_the_model_is_already_converted(calls: list[list[str]]) -> None:
    convert.MODEL_DIR.mkdir(parents=True)
    (convert.MODEL_DIR / SPM_FILE).write_bytes(b"")
    assert convert.main() == 0
    assert calls == []


def test_propagates_the_converter_exit_code(
    calls: list[list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(convert.subprocess, "run", lambda *_a, **_k: Completed(3))
    assert convert.main() == 3


def test_the_revision_is_pinned_to_a_commit() -> None:
    assert len(convert.HF_REVISION) == 40
    int(convert.HF_REVISION, 16)
