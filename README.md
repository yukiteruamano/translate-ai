# Servicio de traducción NLLB (es → en · pt · de · fr · it)

API + UI web para traducir del **español** a **inglés, portugués, alemán, francés e italiano** con
[NLLB-200 distilled 600M](https://huggingface.co/facebook/nllb-200-distilled-600M), ejecutado en **CPU**
con CTranslate2 (int8). Todo en una imagen Docker; el texto no sale del servidor.

> **Licencia del modelo:** los pesos de NLLB-200 son **CC-BY-NC 4.0 (no comercial)** y Meta los publica
> como modelo de investigación. Este servicio es para **pruebas** hasta que Legal valide su uso en Bit2Me.

## Arranque

```bash
docker compose up --build

# Equivalente sin compose: mismo aislamiento y puerto solo en localhost
docker build -t nllb-translate .
docker run --rm --name nllb-translate -p 127.0.0.1:8000:8000 \
  --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges:true \
  --memory 2g --cpus 4 --pids-limit 256 --init --stop-timeout 30 nllb-translate
```

> El `Dockerfile` usa cachés de BuildKit (`--mount=type=cache`): requiere BuildKit, el predeterminado
> en Docker 23+.

- UI: <http://localhost:8000> · Documentación interactiva de la API: <http://localhost:8000/docs>
  (Swagger UI se descarga de un CDN; con `ENABLE_DOCS=0` se desactiva).
- Compose y `docker run` publican el puerto solo en `127.0.0.1`: no hay autenticación. **No uses
  `-p 8000:8000`**, que lo expone en todas las interfaces. Para abrirlo a la red, ponlo tras un gateway/VPN
  con auth y rate-limit por IP y cambia la publicación del puerto.
- Compose limita memoria, CPU y procesos, quita todas las capacidades, monta el sistema de ficheros de solo
  lectura, rota los logs (3 × 10 MB) y da 30 s al apagado (uvicorn espera 25 s a los streams en curso).
- El **build** descarga el modelo oficial (~2,4 GB) y lo convierte a int8; necesita **~3 GB de RAM libres**.
  Es una operación única: el resultado (~600 MB) queda dentro de la imagen y el arranque no descarga nada.
- En ejecución: ~0,8 GB de RAM (pico medido 756 MB) → el `docker-compose.yml` fija 2 GB como margen.

## Despliegue en Coolify

La imagen se construye en CI (`.github/workflows/image.yml`) y se publica en GHCR, así el build no
corre en el servidor de despliegue: la conversión del modelo necesita ~3 GB de RAM libres y descarga
2,4 GB de Hugging Face.

1. En GitHub, publica el paquete y dale acceso al token de registry que uses en Coolify si el repo es privado.
2. En Coolify, recurso **Docker Image** → `ghcr.io/<org>/translate-ia:latest` (o un tag `sha-…` para fijar versión).
3. **Ports Exposes**: `8000`. Dominio interno o de VPN; la UI y la API comparten origen.
4. Healthcheck: el del `Dockerfile`. No hay volúmenes ni base de datos que configurar.
5. Opciones docker del panel para conservar el aislamiento del compose:
   `--read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges:true --memory 2g --cpus 4 --pids-limit 256`.

Variables recomendadas: `CT2_INTRA_THREADS=0`, `MAX_CONCURRENT_REQUESTS=4`, `LOG_LEVEL=INFO`. La API no
tiene autenticación: no la expongas a internet sin gateway con auth y rate-limit por IP. El `docker-compose.yml`
no se usa en Coolify (publica el puerto en `127.0.0.1`, que choca con su proxy).

## API

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/health` | Estado (responde cuando el modelo ya está cargado). |
| `GET` | `/api/languages` | Origen y destinos admitidos. |
| `POST` | `/api/translate` | Un texto → un idioma. |
| `POST` | `/api/translate/batch` | Un texto → varios idiomas en una sola llamada. |
| `POST` | `/api/translate/stream` | Como `translate`, en NDJSON (lo usa la UI). |

Los idiomas se indican con ISO 639-1 (`es`, `en`, `pt`, `de`, `fr`, `it`); también se aceptan los códigos
FLORES-200 de NLLB (`eng_Latn`…). El origen es siempre `es` y se puede omitir.

```bash
curl -X POST http://localhost:8000/api/translate \
  -H 'Content-Type: application/json' \
  -d '{"text": "¿Cómo puedo comprar bitcoin de forma segura?", "target": "en"}'
# {"translation":"How can I buy bitcoin safely?","source":"es","target":"en"}

curl -X POST http://localhost:8000/api/translate/batch \
  -H 'Content-Type: application/json' \
  -d '{"text": "Tu seguridad es nuestra prioridad.", "targets": ["en","pt","de","fr","it"]}'
# {"source":"es","translations":{"en":"Your safety is our priority.","pt":"A sua segurança…", …}}
```

Errores: `400` idioma no soportado o repetido, o texto con caracteres no válidos · `413` texto mayor que
`MAX_INPUT_CHARS` o body demasiado grande · `422` cuerpo inválido · `500` fallo del motor (mensaje
genérico; el detalle va al log) · `503` demasiadas traducciones simultáneas (cabecera `Retry-After`) ·
`504` se superó `REQUEST_TIMEOUT_SECONDS`. En `/api/translate/stream`, los fallos tras abrir el stream
llegan como evento `error` con su `status`. `/api/languages` incluye `max_input_chars` y `docs_enabled`,
que usa la UI (oculta el enlace «API» si `/docs` está desactivado). Las rutas `/api/...` desconocidas
responden `404` en JSON, no con la página de la UI. Los códigos de idioma admiten como máximo 16 caracteres.

Los textos multilínea conservan sus saltos de línea. Internamente se trocean en **frases** (NLLB se
entrenó con frases sueltas y por encima de ~512 tokens degrada; una «palabra» sin espacios mayor que
`MAX_SENTENCE_CHARS` se corta por caracteres para que el encoder no la trunque en silencio), se traducen
por lotes y se cachean (por número de frases y por tamaño total). Las frases se agrupan en **trozos de
~1 500 caracteres** (`MAX_CHUNK_CHARS`): cada trozo se emite por el stream al terminar, de modo que el
primer texto aparece en unos segundos, y si el cliente se desconecta solo se completa el trozo en curso.

## Configuración (variables de entorno)

| Variable | Defecto | Efecto |
|---|---|---|
| `CT2_INTRA_THREADS` | `0` (auto) | Hilos de cálculo. Auto respeta la cuota del contenedor (`--cpus`). |
| `CT2_INTER_THREADS` | `1` | Traducciones en paralelo. Subirlo reparte los hilos entre peticiones. |
| `BEAM_SIZE` | `4` | `1` es más rápido y algo peor; `4` es la calidad de referencia. |
| `MAX_INPUT_CHARS` | `50000` | Tamaño máximo de texto por petición. |
| `MAX_SENTENCE_CHARS` | `400` | Las frases más largas se parten en palabras. |
| `MAX_DECODING_LENGTH` | `256` | Tope de tokens generados por frase. |
| `MAX_CHUNK_CHARS` | `1500` | El texto se traduce y se emite en trozos de este tamaño (frases enteras). Menos = primer resultado y cancelación más rápidos; más = algo más de caudal. |
| `MAX_CONCURRENT_REQUESTS` | `8` | Traducciones en curso o en cola; la siguiente recibe `503`. `0` = sin tope. |
| `REQUEST_TIMEOUT_SECONDS` | `900` | Tiempo máximo por petición, comprobado entre trozos (un trozo en curso se termina). `0` = sin límite. |
| `ENABLE_DOCS` | `1` | `0` desactiva `/docs` y `/openapi.json` (Swagger UI se carga de un CDN). |
| `LOG_LEVEL` | `INFO` | Nivel del logger `nllb_api` (`DEBUG`…`CRITICAL`); cada línea lleva fecha y nivel. |
| `CACHE_SIZE` | `2048` | Frases cacheadas (`0` desactiva); además la caché no supera ~2 M de caracteres. |
| `CORS_ORIGINS` | vacío | Orígenes (coma) que pueden llamar a la API desde un navegador. Cerrado por defecto. |
| `MODEL_DIR` · `STATIC_DIR` · `CT2_COMPUTE_TYPE` | ver `config.py` | Rutas y cuantización. |

## Desarrollo

```bash
cd backend
uv sync --group dev
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q

# Tests con el modelo real (opcional): conviértelo una vez y apunta MODEL_DIR
uv run --group convert python -m nllb_api.convert
MODEL_DIR=models/nllb-200-distilled-600M-int8 uv run pytest -q

# Arrancar el servicio sin Docker (CORS_ORIGINS solo hace falta para `npm run dev`, abajo)
MODEL_DIR=models/nllb-200-distilled-600M-int8 CORS_ORIGINS=http://localhost:3000 \
  uv run uvicorn --factory nllb_api.main:create_app --port 8000

cd ../frontend
npm ci && npm run typecheck && npm run lint && npm run format:check && npm test
NEXT_OUTPUT_EXPORT=1 NEXT_PUBLIC_API_BASE= npm run build   # genera frontend/out (lo sirve la API si STATIC_DIR apunta ahí)
npm run dev                                                # UI en :3000 contra la API en :8000
```

## Decisiones

- **CTranslate2 int8 en lugar de GGUF.** llama.cpp oficial no soporta la arquitectura de NLLB (M2M100);
  los GGUF del Hub dependen de `nllb.cpp`, un motor minoritario, y pesan 1,0–1,24 GB frente a ~0,6 GB.
  CTranslate2 es la opción madura y más eficiente para traducción en CPU.
- **SentencePiece directo, sin `transformers` ni `torch` en runtime.** Solo el stage de conversión los usa.
- **Modelo 600M.** Es el NLLB oficial más pequeño: no existe un NLLB de 200M (el «200» son los idiomas).
- **Sin autenticación.** Para un piloto interno basta; antes de exponerlo, ponlo tras un gateway/VPN o añade API key.
  La API se protege sola con límite de tamaño de body, tope de peticiones simultáneas y timeout, pero el
  rate-limit por IP corresponde al gateway.
- **Build reproducible.** El conversor descarga un snapshot completo de `HF_REVISION` y convierte desde
  disco: pesos, tokenizador y `sentencepiece.bpe.model` salen de la misma revisión (el conversor de
  CTranslate2 solo fija la revisión de los pesos). El stage del modelo solo copia `convert.py`, de modo
  que editar la API no repite la descarga de 2,4 GB, y el modelo va en la primera capa del runtime.
  Las imágenes base van fijadas por digest (`@sha256:…`, ver los `ARG` del `Dockerfile`) y `npm`, `uv` y
  la descarga de Hugging Face usan cachés de BuildKit, así que un fallo de red no repite los 2,4 GB.
  La UI usa la fuente del paquete `geist` (autoalojada): el build no necesita Google Fonts.
- **CI.** `.github/workflows/ci.yml` ejecuta lint, tipos y tests del backend y del frontend, `hadolint`
  sobre el `Dockerfile` y valida el compose. No construye la imagen (descarga el modelo, ~2,4 GB).
- **Cabeceras de seguridad.** `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy` y una CSP de mismo
  origen (la UI exportada usa scripts en línea). `/docs` queda sin CSP porque carga Swagger de un CDN.
- **UI:** adaptada de [sioaeko/NLLB_translator](https://github.com/sioaeko/NLLB_translator) (MIT, ver
  `THIRD_PARTY/`), sin selector de motor, claves de API ni los demás motores. Los avisos de licencia
  (MIT de la UI y OFL de la fuente Geist) van dentro de la imagen y el pie de la UI los enlaza
  (`/licenses/…`).

## Limitaciones conocidas

- **Calidad**: es un modelo de 600M. En pruebas es buena en frases claras, pero hay errores léxicos
  (p. ej. «subidas moderadas» → it. «moderate altezze»; «¿cómo estás?» → en. «Hey, how you doing?»).
  No respeta glosarios ni nombres de marca, y HTML/markdown se desordena. Para contenido legal, MiCA o
  de marca, revisión humana.
- **Latencia en CPU**: del orden de 1 s por frase corta y varios segundos por un párrafo, por idioma
  (medido en una máquina saturada: tómalo como orientativo). Una petición `batch` con 5 idiomas multiplica ese coste.
- **Concurrencia**: con `CT2_INTER_THREADS=1` las peticiones simultáneas se encolan. Para más caudal,
  escala con réplicas del contenedor.
