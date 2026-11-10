"""Protecciones HTTP: tamaño de body, cabeceras de seguridad y tope de concurrencia."""

from __future__ import annotations

import json
from threading import Lock
from types import TracebackType

from fastapi import HTTPException
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_TOO_LARGE = "La petición es demasiado grande."
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})
_DOCS_PATHS = ("/docs", "/redoc")

# La UI exportada de Next.js usa scripts y estilos en línea; todo lo demás es del mismo origen.
_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
    "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


class BodyLimitMiddleware:
    """Responde 413 sin cargar en memoria bodies mayores que `max_bytes`.

    Comprueba `Content-Length` y, para transferencias sin él (chunked), cuenta los
    bytes recibidos. Pydantic solo valida después de leer el body entero.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in _BODY_METHODS:
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > self.max_bytes:
            await self._reject(send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # Debe ser HTTPException: FastAPI convierte cualquier otra excepción
                    # al leer el body en un 400 genérico.
                    raise HTTPException(413, _TOO_LARGE)
            return message

        await self.app(scope, limited_receive, send)

    async def _reject(self, send: Send) -> None:
        body = json.dumps({"detail": _TOO_LARGE}).encode()
        headers = [(b"content-type", b"application/json"), (b"content-length", b"%d" % len(body))]
        await send({"type": "http.response.start", "status": 413, "headers": headers})
        await send({"type": "http.response.body", "body": body})


class SecurityHeadersMiddleware:
    """Cabeceras anti-sniffing/clickjacking y CSP. `/docs` carga Swagger de un CDN: sin CSP."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        is_docs = any(path == p or path.startswith(p + "/") for p in _DOCS_PATHS)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in _SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
                if not is_docs:
                    headers.setdefault("Content-Security-Policy", _CSP)
            await send(message)

        await self.app(scope, receive, send_with_headers)


class ServerBusyError(Exception):
    """Se alcanzó el máximo de traducciones simultáneas."""


class Slot:
    """Plaza de concurrencia. `release` es idempotente: se puede llamar desde varios sitios."""

    def __init__(self, gate: ConcurrencyGate) -> None:
        self._gate = gate
        self._released = False

    def release(self) -> None:
        self._gate.release_slot(self)

    def __enter__(self) -> Slot:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


class ConcurrencyGate:
    """Limita las traducciones en curso o en cola; rechaza en vez de encolar sin fin.

    `limit == 0` desactiva el tope.
    """

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._active = 0
        self._lock = Lock()

    def acquire(self) -> Slot:
        with self._lock:
            if self._limit and self._active >= self._limit:
                raise ServerBusyError
            self._active += 1
        return Slot(self)

    def release_slot(self, slot: Slot) -> None:
        with self._lock:
            if slot._released:  # noqa: SLF001 — el estado del slot lo protege el lock del gate
                return
            slot._released = True  # noqa: SLF001
            self._active -= 1

    @property
    def active(self) -> int:
        return self._active
