"""Configuración por variables de entorno, validada al arrancar."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


def _int(env: Mapping[str, str], name: str, default: int, minimum: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} debe ser un entero, recibido {raw!r}") from None
    if value < minimum:
        raise ValueError(f"{name} debe ser >= {minimum}, recibido {value}")
    return value


_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


def _flag(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in _TRUE | _FALSE:
        return raw in _TRUE
    raise ValueError(f"{name} debe ser 0/1, true/false, yes/no u on/off, recibido {raw!r}")


_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


def _log_level(env: Mapping[str, str]) -> str:
    raw = env.get("LOG_LEVEL", "").strip().upper()
    if not raw:
        return "INFO"
    if raw not in _LOG_LEVELS:
        raise ValueError(f"LOG_LEVEL debe ser uno de {sorted(_LOG_LEVELS)}, recibido {raw!r}")
    return raw


@dataclass(frozen=True)
class Settings:
    model_dir: Path
    static_dir: Path
    compute_type: str
    intra_threads: int  # 0 = autodetectar según cgroup/afinidad
    inter_threads: int
    beam_size: int
    max_decoding_length: int
    max_input_chars: int
    max_sentence_chars: int
    max_chunk_chars: int
    cache_size: int
    max_concurrent_requests: int  # 0 = sin tope
    request_timeout_seconds: int  # 0 = sin límite
    enable_docs: bool
    cors_origins: tuple[str, ...]
    log_level: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        origins = tuple(o.strip() for o in env.get("CORS_ORIGINS", "").split(",") if o.strip())
        return cls(
            model_dir=Path(env.get("MODEL_DIR", "models/nllb-200-distilled-600M-int8")),
            static_dir=Path(env.get("STATIC_DIR", "static")),
            compute_type=env.get("CT2_COMPUTE_TYPE", "int8"),
            intra_threads=_int(env, "CT2_INTRA_THREADS", 0, 0),
            inter_threads=_int(env, "CT2_INTER_THREADS", 1, 1),
            beam_size=_int(env, "BEAM_SIZE", 4, 1),
            max_decoding_length=_int(env, "MAX_DECODING_LENGTH", 256, 8),
            max_input_chars=_int(env, "MAX_INPUT_CHARS", 50_000, 1),
            max_sentence_chars=_int(env, "MAX_SENTENCE_CHARS", 400, 20),
            max_chunk_chars=_int(env, "MAX_CHUNK_CHARS", 1_500, 1),
            cache_size=_int(env, "CACHE_SIZE", 2048, 0),
            max_concurrent_requests=_int(env, "MAX_CONCURRENT_REQUESTS", 8, 0),
            request_timeout_seconds=_int(env, "REQUEST_TIMEOUT_SECONDS", 900, 0),
            enable_docs=_flag(env, "ENABLE_DOCS", True),
            cors_origins=origins,
            log_level=_log_level(env),
        )
