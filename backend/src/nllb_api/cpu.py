"""Hilos de CPU realmente disponibles dentro de un contenedor."""

from __future__ import annotations

import os
from pathlib import Path

_CGROUP = Path("/sys/fs/cgroup")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return ""


def _quota_cpus() -> int | None:
    """Cuota de CPU del cgroup (v2 `cpu.max`, v1 `cpu.cfs_*`), p. ej. `docker --cpus=2`."""
    quota_period = _read(_CGROUP / "cpu.max").split()
    if len(quota_period) == 2 and quota_period[0] != "max":
        quota, period = quota_period
    else:
        quota = _read(_CGROUP / "cpu" / "cpu.cfs_quota_us")
        period = _read(_CGROUP / "cpu" / "cpu.cfs_period_us")
    try:
        if int(quota) > 0 and int(period) > 0:
            return max(1, int(quota) // int(period))
    except ValueError:
        pass
    return None


def available_cpus() -> int:
    """Mínimo entre afinidad y cuota.

    `os.cpu_count()` devuelve los núcleos del host aunque el contenedor tenga un
    límite; un pool de hilos mayor que la cuota pierde tiempo en throttling.
    """
    limits = [len(os.sched_getaffinity(0))]
    quota = _quota_cpus()
    if quota is not None:
        limits.append(quota)
    return max(1, min(limits))
