"""Servido de la UI estática: errores JSON bajo `/api`, caché y compresión gzip."""

from __future__ import annotations

import gzip

from fastapi import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_IMMUTABLE = "public, max-age=31536000, immutable"
# Los assets de `_next/static` llevan un hash en el nombre; el resto se revalida por ETag.
_REVALIDATE = "no-cache"
_HASHED_PREFIX = "_next/static/"
_COMPRESSIBLE = (b"text/", b"application/javascript", b"application/json", b"image/svg+xml")
_MIN_GZIP_BYTES = 512


class UiFiles(StaticFiles):
    """`StaticFiles` montado en `/`: no responde con HTML a rutas `/api/...` desconocidas."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Not Found")
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            hashed = path.startswith(_HASHED_PREFIX)
            response.headers["Cache-Control"] = _IMMUTABLE if hashed else _REVALIDATE
        return response


def _wants_gzip(scope: Scope) -> bool:
    return b"gzip" in dict(scope["headers"]).get(b"accept-encoding", b"")


def _is_compressible(start: Message) -> bool:
    content_type: bytes = dict(start["headers"]).get(b"content-type", b"")
    return bool(start["status"] == 200 and content_type.startswith(_COMPRESSIBLE))


class GzipStatic:
    """Comprime solo la UI. `GZipMiddleware` global retendría el NDJSON de `/translate/stream`.

    Los ficheros estáticos son pequeños: se acumula el cuerpo y se comprime de una vez.
    Todo lo que no sea un 200 comprimible pasa sin tocar.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _wants_gzip(scope):
            await self.app(scope, receive, send)
            return
        # `pathsend` enviaría el fichero sin pasar por aquí: no se puede comprimir.
        extensions = scope.get("extensions") or {}
        scope = {
            **scope,
            "extensions": {k: v for k, v in extensions.items() if "pathsend" not in k},
        }

        start: Message | None = None
        compress = False
        body = bytearray()

        async def gzip_send(message: Message) -> None:
            nonlocal start, compress
            if message["type"] == "http.response.start":
                compress = _is_compressible(message)
                if compress:
                    start = message
                    return
            elif compress and message["type"] == "http.response.body":
                body.extend(message.get("body", b""))
                if not message.get("more_body") and start is not None:
                    await self._send_compressed(start, bytes(body), send)
                return
            await send(message)

        await self.app(scope, receive, gzip_send)

    @staticmethod
    async def _send_compressed(start: Message, body: bytes, send: Send) -> None:
        headers = [(k, v) for k, v in start["headers"] if k.lower() != b"content-length"]
        if len(body) >= _MIN_GZIP_BYTES:
            body = gzip.compress(body, compresslevel=6, mtime=0)
            headers += [(b"content-encoding", b"gzip"), (b"vary", b"Accept-Encoding")]
        headers.append((b"content-length", b"%d" % len(body)))
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": body})
