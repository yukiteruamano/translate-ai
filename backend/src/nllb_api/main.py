"""API HTTP: traducción es → en/pt/de/fr/it y, si existe, la UI estática.

Arranque: `uvicorn --factory nllb_api.main:create_app`
"""

from __future__ import annotations

import json
import logging
import time
import weakref
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from nllb_api.config import Settings
from nllb_api.engine import Engine, NllbEngine
from nllb_api.languages import (
    SOURCE,
    TARGETS,
    Language,
    UnsupportedLanguageError,
    resolve_source,
    resolve_target,
)
from nllb_api.security import (
    BodyLimitMiddleware,
    ConcurrencyGate,
    SecurityHeadersMiddleware,
    ServerBusyError,
    Slot,
)
from nllb_api.service import TranslationTimeoutError, stream_translation, translate_text
from nllb_api.ui import GzipStatic, UiFiles

logger = logging.getLogger("nllb_api")

MODEL_NAME = "nllb-200-distilled-600M"
# Peor caso de un carácter en JSON: un par sustituto escapado (`\uXXXX\uXXXX`), 12 bytes.
_MAX_JSON_BYTES_PER_CHAR = 12
_BODY_OVERHEAD_BYTES = 4096
_BUSY_RETRY_SECONDS = 5

_ERROR_FAILED = "La traducción ha fallado."
_ERROR_TIMEOUT = "La traducción ha tardado demasiado. Prueba con un texto más corto."
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# Un código de idioma mide como mucho 8 caracteres (`spa_Latn`): el resto es basura.
LanguageCode = Annotated[str, Field(max_length=16)]


class TranslateRequest(BaseModel):
    text: str = Field(description="Texto a traducir. Se conservan los saltos de línea.")
    source: LanguageCode = Field(default=SOURCE.code, description="Idioma de origen: `es`.")
    target: LanguageCode = Field(description="Destino: `en`, `pt`, `de`, `fr` o `it`.")


class TranslateResponse(BaseModel):
    translation: str
    source: str
    target: str


class BatchRequest(BaseModel):
    text: str = Field(description="Texto a traducir. Se conservan los saltos de línea.")
    source: LanguageCode = Field(default=SOURCE.code, description="Idioma de origen: `es`.")
    targets: list[LanguageCode] = Field(
        min_length=1, max_length=len(TARGETS), description="Destinos, sin repetir."
    )


class BatchResponse(BaseModel):
    source: str
    translations: dict[str, str] = Field(description="Traducción por código de idioma destino.")


class LanguageInfo(BaseModel):
    code: str
    name: str


class LanguagesResponse(BaseModel):
    source: LanguageInfo
    targets: list[LanguageInfo]
    max_input_chars: int = Field(description="Longitud máxima del texto por petición.")
    docs_enabled: bool = Field(description="Si `/docs` (Swagger UI) está disponible.")


def _engine(request: Request) -> Engine:
    engine: Engine = request.app.state.engine
    return engine


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _gate(request: Request) -> ConcurrencyGate:
    gate: ConcurrencyGate = request.app.state.gate
    return gate


EngineDep = Annotated[Engine, Depends(_engine)]
SettingsDep = Annotated[Settings, Depends(_settings)]
GateDep = Annotated[ConcurrencyGate, Depends(_gate)]


def _check_text(text: str, settings: Settings) -> None:
    if len(text) > settings.max_input_chars:
        raise HTTPException(413, f"Texto demasiado largo (máximo {settings.max_input_chars}).")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        # JSON admite `\ud800` suelto; no es texto válido y rompería tokenizador y respuesta.
        raise HTTPException(400, "El texto contiene caracteres no válidos.") from None


def _resolve(resolver: Callable[[str], Language], value: str) -> Language:
    try:
        return resolver(value)
    except UnsupportedLanguageError as exc:
        raise HTTPException(400, str(exc)) from exc


def _acquire(gate: ConcurrencyGate) -> Slot:
    try:
        return gate.acquire()
    except ServerBusyError:
        raise HTTPException(
            503,
            "El servidor está ocupado con otras traducciones. Inténtalo de nuevo en unos segundos.",
            headers={"Retry-After": str(_BUSY_RETRY_SECONDS)},
        ) from None


def _deadline(settings: Settings) -> float | None:
    seconds = settings.request_timeout_seconds
    return time.monotonic() + seconds if seconds else None


def _translate(
    engine: Engine,
    settings: Settings,
    text: str,
    source: Language,
    target: Language,
    deadline: float | None,
) -> str:
    try:
        return translate_text(
            engine,
            text,
            source,
            target,
            settings.max_sentence_chars,
            settings.max_chunk_chars,
            deadline=deadline,
        )
    except TranslationTimeoutError as exc:
        logger.warning("Traducción cancelada por tiempo máximo")
        raise HTTPException(504, _ERROR_TIMEOUT) from exc
    except Exception as exc:
        logger.exception("Fallo de traducción")
        raise HTTPException(500, _ERROR_FAILED) from exc


def _packet(data: dict[str, object]) -> str:
    return json.dumps(data, ensure_ascii=False) + "\n"


def _error_packet(detail: str, status: int) -> str:
    return _packet({"type": "error", "detail": detail, "status": status})


def _stream_events(
    engine: Engine,
    settings: Settings,
    text: str,
    source: Language,
    target: Language,
    slot: Slot,
) -> Iterator[str]:
    parts: list[str] = []
    try:
        for piece in stream_translation(
            engine,
            text,
            source,
            target,
            settings.max_sentence_chars,
            settings.max_chunk_chars,
            deadline=_deadline(settings),
        ):
            parts.append(piece)
            if piece:
                yield _packet({"type": "delta", "text": piece})
        yield _packet(
            {
                "type": "done",
                "translation": "".join(parts),
                "source": source.code,
                "target": target.code,
            }
        )
    except TranslationTimeoutError:
        logger.warning("Traducción en streaming cancelada por tiempo máximo")
        yield _error_packet(_ERROR_TIMEOUT, 504)
    except Exception:
        logger.exception("Fallo de traducción en streaming")
        yield _error_packet(_ERROR_FAILED, 500)
    finally:
        slot.release()


def _configure_logging(level: str) -> None:
    """Formato con fecha y nivel para `nllb_api`; uvicorn solo configura sus propios loggers."""
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        logger.addHandler(handler)


def create_app(
    settings: Settings | None = None,
    engine_factory: Callable[[Settings], Engine] = NllbEngine,
) -> FastAPI:
    settings = settings or Settings.from_env()
    _configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Cargar aquí hace que el servicio no acepte tráfico hasta tener el modelo listo.
        app.state.engine = engine_factory(settings)
        yield

    app = FastAPI(
        title="NLLB Translate API",
        description="Traduce del español a inglés, portugués, alemán, francés e italiano "
        "con NLLB-200 (600M destilado) en CPU. "
        f"Texto máximo por petición: {settings.max_input_chars} caracteres.",
        version="0.1.0",
        lifespan=lifespan,
        # Swagger UI se carga de un CDN: ENABLE_DOCS=0 lo desactiva en despliegues aislados.
        docs_url="/docs" if settings.enable_docs else None,
        openapi_url="/openapi.json" if settings.enable_docs else None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.gate = ConcurrencyGate(settings.max_concurrent_requests)

    # El último middleware añadido es el más externo: las cabeceras de seguridad cubren
    # también los 413 y las respuestas CORS.
    app.add_middleware(
        BodyLimitMiddleware,
        max_bytes=settings.max_input_chars * _MAX_JSON_BYTES_PER_CHAR + _BODY_OVERHEAD_BYTES,
    )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
        )
    app.add_middleware(SecurityHeadersMiddleware)

    # `async def`: corre en el bucle de eventos, así que responde aunque el threadpool
    # (40 hilos) esté ocupado por traducciones.
    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "model": MODEL_NAME}

    @app.get("/api/languages", response_model=LanguagesResponse)
    def languages(settings: SettingsDep) -> LanguagesResponse:
        return LanguagesResponse(
            source=LanguageInfo(code=SOURCE.code, name=SOURCE.name),
            targets=[LanguageInfo(code=t.code, name=t.name) for t in TARGETS],
            max_input_chars=settings.max_input_chars,
            docs_enabled=settings.enable_docs,
        )

    @app.post("/api/translate", response_model=TranslateResponse)
    def translate(
        req: TranslateRequest, engine: EngineDep, settings: SettingsDep, gate: GateDep
    ) -> TranslateResponse:
        source, target = _resolve(resolve_source, req.source), _resolve(resolve_target, req.target)
        _check_text(req.text, settings)
        with _acquire(gate):
            translation = _translate(
                engine, settings, req.text, source, target, _deadline(settings)
            )
        return TranslateResponse(translation=translation, source=source.code, target=target.code)

    @app.post("/api/translate/batch", response_model=BatchResponse)
    def translate_batch(
        req: BatchRequest, engine: EngineDep, settings: SettingsDep, gate: GateDep
    ) -> BatchResponse:
        source = _resolve(resolve_source, req.source)
        targets = [_resolve(resolve_target, t) for t in req.targets]
        if len({t.code for t in targets}) != len(targets):
            raise HTTPException(400, "Hay idiomas de destino repetidos.")
        _check_text(req.text, settings)
        deadline = _deadline(settings)  # un único presupuesto de tiempo para todos los idiomas
        with _acquire(gate):
            translations = {
                t.code: _translate(engine, settings, req.text, source, t, deadline) for t in targets
            }
        return BatchResponse(source=source.code, translations=translations)

    @app.post("/api/translate/stream")
    def translate_stream(
        req: TranslateRequest, engine: EngineDep, settings: SettingsDep, gate: GateDep
    ) -> StreamingResponse:
        # Los errores de validación salen como HTTP 4xx antes de abrir el stream.
        source, target = _resolve(resolve_source, req.source), _resolve(resolve_target, req.target)
        _check_text(req.text, settings)
        slot = _acquire(gate)
        events = _stream_events(engine, settings, req.text, source, target, slot)
        # La plaza se libera al terminar el generador; si nunca llega a arrancar (cliente
        # que se va antes del primer trozo) lo hacen el finalizador y la tarea de fondo.
        weakref.finalize(events, slot.release)
        return StreamingResponse(
            events,
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
            background=BackgroundTask(slot.release),
        )

    # La UI va al final: las rutas /api y /docs tienen prioridad sobre el montaje en "/".
    if settings.static_dir.is_dir():
        ui = UiFiles(directory=settings.static_dir, html=True)
        app.mount("/", GzipStatic(ui), name="static")

    return app
