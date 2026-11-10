from __future__ import annotations

from pathlib import Path

import pytest

from nllb_api import cpu


@pytest.fixture
def cgroup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(cpu, "_CGROUP", tmp_path)
    monkeypatch.setattr(cpu.os, "sched_getaffinity", lambda _pid: set(range(8)))
    return tmp_path


def write(root: Path, name: str, content: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_without_cgroup_files_uses_the_affinity(cgroup: Path) -> None:
    assert cpu.available_cpus() == 8


def test_cgroup_v2_quota(cgroup: Path) -> None:
    write(cgroup, "cpu.max", "200000 100000\n")
    assert cpu.available_cpus() == 2


def test_cgroup_v2_without_limit_falls_back_to_affinity(cgroup: Path) -> None:
    write(cgroup, "cpu.max", "max 100000\n")
    assert cpu.available_cpus() == 8


def test_cgroup_v1_quota(cgroup: Path) -> None:
    write(cgroup, "cpu/cpu.cfs_quota_us", "300000\n")
    write(cgroup, "cpu/cpu.cfs_period_us", "100000\n")
    assert cpu.available_cpus() == 3


def test_cgroup_v1_unlimited_is_ignored(cgroup: Path) -> None:
    write(cgroup, "cpu/cpu.cfs_quota_us", "-1\n")
    write(cgroup, "cpu/cpu.cfs_period_us", "100000\n")
    assert cpu.available_cpus() == 8


def test_fractional_quota_rounds_down_but_never_below_one(cgroup: Path) -> None:
    write(cgroup, "cpu.max", "50000 100000\n")
    assert cpu.available_cpus() == 1


def test_the_smaller_of_quota_and_affinity_wins(
    cgroup: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(cgroup, "cpu.max", "400000 100000\n")
    monkeypatch.setattr(cpu.os, "sched_getaffinity", lambda _pid: {0, 1})
    assert cpu.available_cpus() == 2


@pytest.mark.parametrize("content", ["basura", "x y", "100000", ""])
def test_malformed_cgroup_files_are_ignored(cgroup: Path, content: str) -> None:
    write(cgroup, "cpu.max", content)
    assert cpu.available_cpus() == 8
