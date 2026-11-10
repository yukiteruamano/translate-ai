"""Descarga NLLB-200 de Hugging Face y lo convierte a CTranslate2 int8.

Se ejecuta una vez en el build de la imagen (necesita el grupo `convert`: torch):

    python -m nllb_api.convert

Genera ~600 MB en MODEL_DIR (el checkpoint original pesa ~2,4 GB en fp32) y copia
el modelo SentencePiece, que el runtime usa para tokenizar sin `transformers`.
"""

from __future__ import annotations

import os
import subprocess  # noqa: S404 — el conversor de CTranslate2 solo expone CLI estable
import sys
from pathlib import Path

from nllb_api.constants import SPM_FILE

HF_MODEL = os.environ.get("HF_MODEL", "facebook/nllb-200-distilled-600M")
# Fijar la revisión evita que un cambio aguas arriba altere la imagen sin avisar.
HF_REVISION = os.environ.get("HF_REVISION", "f8d333a098d19b4fd9a8b18f94170487ad3f821d")
MODEL_DIR = Path(os.environ.get("MODEL_DIR", "models/nllb-200-distilled-600M-int8"))
QUANTIZATION = os.environ.get("CT2_COMPUTE_TYPE", "int8")


def _download_snapshot() -> str:
    """Descarga todos los ficheros del repo en `HF_REVISION`.

    El conversor de CTranslate2 solo aplica `--revision` a los pesos: el tokenizador y
    `sentencepiece.bpe.model` los pediría a `main`. Convertir desde un directorio local
    hace que todo salga de la misma revisión.
    """
    from huggingface_hub import snapshot_download

    return str(snapshot_download(HF_MODEL, revision=HF_REVISION))


def main() -> int:
    if (MODEL_DIR / SPM_FILE).is_file():
        print(f"Modelo ya convertido en {MODEL_DIR}.")
        return 0
    MODEL_DIR.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "ctranslate2.converters.transformers",
        "--model",
        _download_snapshot(),
        "--output_dir",
        str(MODEL_DIR),
        "--quantization",
        QUANTIZATION,
        "--copy_files",
        SPM_FILE,
        # Evita tener a la vez pesos aleatorios y checkpoint completo en memoria.
        "--low_cpu_mem_usage",
    ]
    print("Ejecutando:", " ".join(command), flush=True)
    return subprocess.run(command, check=False).returncode  # noqa: S603


if __name__ == "__main__":
    raise SystemExit(main())
