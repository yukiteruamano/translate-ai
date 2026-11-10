from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.fakes import BrokenEngine, FakeEngine

from nllb_api.config import Settings
from nllb_api.main import create_app


def test_health_and_languages(client: TestClient) -> None:
    assert client.get("/api/health").json()["status"] == "ok"
    body = client.get("/api/languages").json()
    assert body["source"]["code"] == "es"
    assert [t["code"] for t in body["targets"]] == ["en", "pt", "de", "fr", "it"]
    assert body["max_input_chars"] == 200


def test_translate_multiline_keeps_line_breaks(client: TestClient, engine: FakeEngine) -> None:
    res = client.post("/api/translate", json={"text": "Hola. Adiós.\n\nOtra línea", "target": "en"})
    assert res.status_code == 200
    assert res.json() == {
        "translation": "[en] Hola. [en] Adiós.\n\n[en] Otra línea",
        "source": "es",
        "target": "en",
    }
    assert engine.calls == [(["Hola.", "Adiós.", "Otra línea"], "en")]


def test_translate_accepts_flores_codes(client: TestClient) -> None:
    res = client.post(
        "/api/translate", json={"text": "Hola", "source": "spa_Latn", "target": "deu_Latn"}
    )
    assert res.json()["target"] == "de"


def test_batch_returns_every_target(client: TestClient) -> None:
    res = client.post("/api/translate/batch", json={"text": "Hola", "targets": ["en", "it"]})
    assert res.json() == {"source": "es", "translations": {"en": "[en] Hola", "it": "[it] Hola"}}


def test_batch_rejects_duplicates_and_empty_targets(client: TestClient) -> None:
    dup = client.post("/api/translate/batch", json={"text": "Hola", "targets": ["en", "en"]})
    assert dup.status_code == 400
    empty = client.post("/api/translate/batch", json={"text": "Hola", "targets": []})
    assert empty.status_code == 422


def test_rejects_unsupported_languages(client: TestClient) -> None:
    assert client.post("/api/translate", json={"text": "x", "target": "ja"}).status_code == 400
    bad_source = {"text": "x", "source": "en", "target": "fr"}
    assert client.post("/api/translate", json=bad_source).status_code == 400


def test_rejects_oversized_text(client: TestClient) -> None:
    res = client.post("/api/translate", json={"text": "a" * 201, "target": "en"})
    assert res.status_code == 413


def test_empty_text_returns_empty_translation(client: TestClient) -> None:
    res = client.post("/api/translate", json={"text": "  \n ", "target": "en"})
    assert res.json()["translation"] == "\n"


def test_stream_emits_one_delta_per_chunk_then_done(engine: FakeEngine, tmp_path: Path) -> None:
    settings = Settings.from_env({"STATIC_DIR": str(tmp_path / "sin-ui"), "MAX_CHUNK_CHARS": "5"})
    with TestClient(create_app(settings, lambda _: engine)) as client:
        res = client.post("/api/translate/stream", json={"text": "Uno.\nDos.", "target": "pt"})
    assert res.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in res.text.splitlines()]
    assert [e["type"] for e in events] == ["delta", "delta", "done"]
    assert events[-1]["translation"] == "[pt] Uno.\n[pt] Dos."


def test_stream_validation_errors_are_http_errors(client: TestClient) -> None:
    assert (
        client.post("/api/translate/stream", json={"text": "x", "target": "ja"}).status_code == 400
    )


def test_engine_failure_does_not_leak_details(settings: Settings) -> None:
    with TestClient(create_app(settings, lambda _: BrokenEngine())) as client:
        res = client.post("/api/translate", json={"text": "Hola", "target": "en"})
        assert res.status_code == 500
        assert "interno" not in res.text
        stream = client.post("/api/translate/stream", json={"text": "Hola", "target": "en"})
        last = json.loads(stream.text.splitlines()[-1])
        assert last == {"type": "error", "detail": "La traducción ha fallado.", "status": 500}


def test_serves_static_ui_without_shadowing_api(tmp_path: Path, engine: FakeEngine) -> None:
    (tmp_path / "index.html").write_text("<h1>UI</h1>")
    settings = Settings.from_env({"STATIC_DIR": str(tmp_path)})
    with TestClient(create_app(settings, lambda _: engine)) as client:
        assert "<h1>UI</h1>" in client.get("/").text
        assert client.get("/api/health").json()["status"] == "ok"


def test_cors_is_closed_by_default(client: TestClient) -> None:
    res = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in res.headers


JSON = {"Content-Type": "application/json"}


def test_lone_surrogates_are_a_client_error_not_a_server_error(client: TestClient) -> None:
    body = '{"text": "hola \\ud800", "target": "en"}'
    assert client.post("/api/translate", content=body, headers=JSON).status_code == 400
    assert client.post("/api/translate/stream", content=body, headers=JSON).status_code == 400
    batch = '{"text": "\\udc00", "targets": ["en"]}'
    assert client.post("/api/translate/batch", content=batch, headers=JSON).status_code == 400


def test_oversized_body_is_rejected_by_content_length(client: TestClient) -> None:
    res = client.post("/api/translate", content=b" " * 10_000, headers=JSON)
    assert res.status_code == 413
    assert res.json() == {"detail": "La petición es demasiado grande."}


def test_oversized_chunked_body_is_rejected_without_content_length(client: TestClient) -> None:
    res = client.post("/api/translate", content=iter([b" " * 4000, b" " * 4000]), headers=JSON)
    assert "content-length" not in res.request.headers
    assert res.status_code == 413
    assert res.json() == {"detail": "La petición es demasiado grande."}


def test_security_headers_on_api_and_csp_skipped_for_docs(client: TestClient) -> None:
    api = client.get("/api/health")
    assert api.headers["x-content-type-options"] == "nosniff"
    assert api.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in api.headers["content-security-policy"]
    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "content-security-policy" not in docs.headers
    assert docs.headers["x-content-type-options"] == "nosniff"


def test_docs_can_be_disabled(tmp_path: Path, engine: FakeEngine) -> None:
    settings = Settings.from_env({"STATIC_DIR": str(tmp_path / "x"), "ENABLE_DOCS": "0"})
    with TestClient(create_app(settings, lambda _: engine)) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/languages").json()["docs_enabled"] is False


def test_docs_are_advertised_when_enabled(client: TestClient) -> None:
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/api/languages").json()["docs_enabled"] is True


def test_language_codes_are_length_limited(client: TestClient) -> None:
    long = "x" * 17
    assert client.post("/api/translate", json={"text": "a", "target": long}).status_code == 422
    assert (
        client.post(
            "/api/translate", json={"text": "a", "target": "en", "source": long}
        ).status_code
        == 422
    )
    batch = client.post("/api/translate/batch", json={"text": "a", "targets": [long]})
    assert batch.status_code == 422


def test_unknown_api_paths_are_json_not_the_ui(tmp_path: Path, engine: FakeEngine) -> None:
    (tmp_path / "index.html").write_text("<h1>UI</h1>")
    (tmp_path / "404.html").write_text("<h1>no</h1>")
    settings = Settings.from_env({"STATIC_DIR": str(tmp_path)})
    with TestClient(create_app(settings, lambda _: engine)) as client:
        res = client.get("/api/nope")
        assert res.status_code == 404
        assert res.json() == {"detail": "Not Found"}
        assert client.get("/api/translate").status_code == 404
        assert client.get("/otra-ruta").status_code == 404
        assert "<h1>no</h1>" in client.get("/otra-ruta").text


def test_static_assets_are_cached_and_compressed(tmp_path: Path, engine: FakeEngine) -> None:
    (tmp_path / "index.html").write_text("<h1>UI</h1>" + "x" * 2000)
    asset = tmp_path / "_next" / "static" / "app-abc123.js"
    asset.parent.mkdir(parents=True)
    asset.write_text("console.log('hola');" * 200)
    settings = Settings.from_env({"STATIC_DIR": str(tmp_path)})
    with TestClient(create_app(settings, lambda _: engine)) as client:
        js = client.get("/_next/static/app-abc123.js", headers={"Accept-Encoding": "gzip"})
        assert js.headers["content-encoding"] == "gzip"
        assert js.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert js.text == asset.read_text()  # httpx descomprime
        assert int(js.headers["content-length"]) < asset.stat().st_size
        page = client.get("/", headers={"Accept-Encoding": "gzip"})
        assert page.headers["cache-control"] == "no-cache"
        assert page.headers["content-encoding"] == "gzip"
        plain = client.get("/", headers={"Accept-Encoding": "identity"})
        assert "content-encoding" not in plain.headers
        assert plain.text.startswith("<h1>UI</h1>")
        assert "frame-ancestors" in plain.headers["content-security-policy"]


def test_the_stream_is_never_compressed(client: TestClient) -> None:
    res = client.post(
        "/api/translate/stream",
        json={"text": "Hola", "target": "en"},
        headers={"Accept-Encoding": "gzip"},
    )
    assert "content-encoding" not in res.headers


def test_logging_uses_a_timestamped_format(settings: Settings, engine: FakeEngine) -> None:
    import logging

    create_app(settings, lambda _: engine)
    logger = logging.getLogger("nllb_api")
    assert logger.level == logging.INFO
    assert "%(asctime)s" in logger.handlers[0].formatter._fmt  # type: ignore[union-attr]


def test_busy_server_answers_503_and_recovers(engine: FakeEngine, tmp_path: Path) -> None:
    limited = Settings.from_env({"STATIC_DIR": str(tmp_path / "x"), "MAX_CONCURRENT_REQUESTS": "1"})
    app = create_app(limited, lambda _: engine)
    body = {"text": "Hola", "target": "en"}
    with TestClient(app) as client:
        slot = app.state.gate.acquire()
        for path in ("/api/translate", "/api/translate/stream"):
            res = client.post(path, json=body)
            assert res.status_code == 503
            assert res.headers["retry-after"] == "5"
        slot.release()
        assert client.post("/api/translate", json=body).status_code == 200
        assert app.state.gate.active == 0


def test_stream_and_batch_release_their_slot(settings: Settings, engine: FakeEngine) -> None:
    app = create_app(settings, lambda _: engine)
    with TestClient(app) as client:
        client.post("/api/translate/stream", json={"text": "Hola", "target": "en"})
        client.post("/api/translate/batch", json={"text": "Hola", "targets": ["en", "it"]})
        assert app.state.gate.active == 0


def test_timeout_is_a_504_and_a_stream_error_event(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("nllb_api.main._deadline", lambda _settings: time.monotonic() - 1)
    res = client.post("/api/translate", json={"text": "Hola", "target": "en"})
    assert res.status_code == 504
    batch = client.post("/api/translate/batch", json={"text": "Hola", "targets": ["en"]})
    assert batch.status_code == 504
    stream = client.post("/api/translate/stream", json={"text": "Hola", "target": "en"})
    last = json.loads(stream.text.splitlines()[-1])
    assert (last["type"], last["status"]) == ("error", 504)
