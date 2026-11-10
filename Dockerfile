# syntax=docker/dockerfile:1
#
# Imagen única: API FastAPI + UI estática + NLLB-200 600M (CTranslate2 int8, CPU).
#   docker build -t nllb-translate .
#   docker run --rm -p 8000:8000 nllb-translate
#
# El runtime no lleva torch ni transformers: el modelo se convierte en un stage
# aparte y solo se copia el resultado (~600 MB).

# Imágenes fijadas por digest (etiqueta + sha256 de la lista multi-arquitectura): el build
# no cambia aunque se republique la etiqueta. Para actualizarlas, cambia ambos a la vez.
ARG PYTHON_IMAGE=python:3.12-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
ARG NODE_IMAGE=node:22-trixie-slim@sha256:be1e2a3dc2c4fd68cdfadad2a696a280e0d2749098bee509230174d72fb768c6
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490

FROM ${UV_IMAGE} AS uv

# Las cachés de BuildKit (`--mount=type=cache`) no entran en la imagen: un cambio en un
# lockfile o un fallo de red no repite las descargas.

# ---- UI: export estático de Next.js, servido por la propia API (mismo origen) ----
FROM ${NODE_IMAGE} AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-fund
COPY frontend/ ./
ENV NEXT_OUTPUT_EXPORT=1 \
    NEXT_PUBLIC_API_BASE= \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ---- Dependencias del runtime (sin torch) ----
FROM ${PYTHON_IMAGE} AS deps
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# ---- Modelo: descarga de Hugging Face y conversión a int8 (aquí sí hace falta torch) ----
FROM ${PYTHON_IMAGE} AS model
COPY --from=uv /uv /usr/local/bin/uv
# HF_HOME apunta a una caché de BuildKit: el checkpoint de 2,4 GB sobrevive a un fallo
# de red o de memoria durante la conversión y no acaba en ninguna capa de la imagen.
ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    HF_HOME=/hf-cache \
    PYTHONPATH=/app/src \
    MODEL_DIR=/app/models/nllb-200-distilled-600M-int8
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --group convert --no-install-project
# Solo lo que necesita el conversor: así, editar la API no repite la descarga del modelo.
COPY backend/src/nllb_api/__init__.py backend/src/nllb_api/constants.py \
     backend/src/nllb_api/convert.py ./src/nllb_api/
# Necesita ~3 GB de RAM libres durante el build (el checkpoint fp32 pesa 2,4 GB).
RUN --mount=type=cache,target=/hf-cache \
    .venv/bin/python -m nllb_api.convert

# ---- Runtime ----
FROM ${PYTHON_IMAGE} AS runtime
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MODEL_DIR=/app/models/nllb-200-distilled-600M-int8 \
    STATIC_DIR=/app/static
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
# De menos a más cambiante: el modelo (~600 MB) no debe reconstruirse al editar el código.
COPY --from=model /app/models ./models
COPY --from=deps /app/.venv ./.venv
COPY --from=frontend /fe/out ./static
# Avisos de licencia de terceros (UI derivada de código MIT, fuente Geist): la UI enlaza a ellos.
COPY THIRD_PARTY ./static/licenses
COPY backend/src ./src
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"]
# El apagado espera a los streams en curso (un trozo dura segundos); debe ser menor que el
# `stop_grace_period` del compose para que Docker no llegue a enviar SIGKILL.
CMD ["uvicorn", "--factory", "nllb_api.main:create_app", "--host", "0.0.0.0", "--port", "8000", \
     "--timeout-graceful-shutdown", "25"]
