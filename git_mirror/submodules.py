#!/usr/bin/env python3
"""Helpers for mirroring Git submodules."""

from __future__ import annotations
from pathlib import Path
from typing import List

from .core import ensure_mirror, _run


def submodule_urls(repo_dir: Path) -> List[str]:
    """Return submodule URLs defined in the repository's .gitmodules.

    The repository is expected to be a bare mirror. We read the .gitmodules file
    from HEAD using ``git config --blob``. If the repository has no submodules,
    an empty list is returned.
    """
    cp = _run(
        [
            "git",
            "--git-dir",
            str(repo_dir),
            "config",
            "--blob",
            "HEAD:.gitmodules",
            "--get-regexp",
            r"submodule\\..*\\.url",
        ],
        check=False,
    )
    if cp.returncode != 0:
        return []
    urls: List[str] = []
    for line in cp.stdout.strip().splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            urls.append(parts[1])
    return urls


def mirror_submodules(repo_dir: Path, base_dir: Path) -> List[Path]:
    """Mirror all submodules of ``repo_dir`` under ``base_dir``.

    Submodules are processed recursively. Returns a list of paths to mirrored
    submodule repositories.
    """
    mirrored: List[Path] = []
    for url in submodule_urls(repo_dir):
        sub_repo = ensure_mirror(url, base_dir)
        mirrored.append(sub_repo)
        # Recurse into nested submodules
        mirrored.extend(mirror_submodules(sub_repo, base_dir))
    return mirrored
