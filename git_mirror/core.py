#!/usr/bin/env python3
"""
Core utilities for mirroring Git repositories into a GitHub-like folder layout.

Layout:
  <base_dir>/<host>/<path>.git

Examples:
  https://github.com/numpy/numpy.git  -> base/github.com/numpy/numpy.git
  git@github.com:torvalds/linux.git   -> base/github.com/torvalds/linux.git
  https://gitlab.com/group/sub/repo   -> base/gitlab.com/group/sub/repo.git

Notes:
- All path segments after the host are preserved.
- Clones use `--mirror`. Existing mirrors are updated with `git remote update --prune`.
"""

from __future__ import annotations
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional, Tuple, List
from urllib.parse import urlparse
from datetime import datetime

SSH_SCHEME_RE = re.compile(r"""
    ^(?P<user>[A-Za-z0-9._-]+)@(?P<host>[A-Za-z0-9._-]+):
    (?P<path>.+)$
""", re.VERBOSE)


@dataclass(frozen=True)
class RepoID:
    host: str
    path: Tuple[str, ...]  # path components after the host, repo name last

    @property
    def owner(self) -> str:
        return self.path[0] if self.path else ""

    @property
    def name(self) -> str:
        return self.path[-1] if self.path else ""

    def mirror_dir(self, base_dir: Path) -> Path:
        """Return the on-disk path for this repository under ``base_dir``."""
        return base_dir.joinpath(self.host, *self.path[:-1], f"{self.path[-1]}.git")


def _strip_git_suffix(repo: str) -> str:
    return repo[:-4] if repo.endswith(".git") else repo


def _parse_ssh_like(url: str) -> Optional[Tuple[str, str]]:
    """Parse ``git@host:path`` style URLs into ``(host, path)``."""
    m = SSH_SCHEME_RE.match(url)
    if not m:
        return None
    return m.group("host"), m.group("path")


def _split_path(path: str) -> Tuple[str, ...]:
    """Split a repository path into components and drop any trailing ``.git``."""
    parts = [p for p in Path(path).parts if p not in ("/", "")]
    if not parts:
        raise ValueError(f"Cannot parse path from empty string: {path}")
    parts[-1] = _strip_git_suffix(parts[-1])
    if parts[-1] in ("", ".", ".."):
        raise ValueError(f"Suspicious repo segment parsed from path: {path}")
    return tuple(parts)


def parse_repo_id(url: str) -> RepoID:
    """Parse a Git URL (SSH/HTTP/etc.) into ``RepoID(host, path)``."""
    # SSH style: git@host:path
    ssh = _parse_ssh_like(url)
    if ssh is not None:
        host, path = ssh
        return RepoID(host=host, path=_split_path(path))

    # HTTP(S) style
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https", "ssh", "git"):
        host = parsed.hostname or ""
        if not host:
            raise ValueError(f"Missing host in URL: {url}")
        # parsed.path starts with '/', remove it for clean splitting
        return RepoID(host=host, path=_split_path(parsed.path.lstrip("/")))

    # Local path fallback (less common for your use case, but harmless)
    if os.path.exists(url):
        # Treat local path as /owner/repo(.git), where owner is parent folder name
        p = Path(url).resolve()
        if p.is_dir() and p.name.endswith(".git"):
            repo = _strip_git_suffix(p.name)
            owner = p.parent.name or "_local"
            return RepoID(host="_local", path=(owner, repo))
        raise ValueError(f"Local path provided is not a mirror dir: {url}")

    raise ValueError(f"Unsupported URL format: {url}")


def _run(cmd: List[str], cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def ensure_mirror(url: str, base_dir: Path) -> Path:
    """
    Ensure a repository is mirror-cloned under ``base_dir`` in
    ``host/<path>.git``. If already present, do a remote update; otherwise
    perform ``git clone --mirror``. Returns the path to the mirror directory.
    """
    rid = parse_repo_id(url)
    target = rid.mirror_dir(base_dir)

    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        # Update existing mirror
        _run(["git", "remote", "update", "--prune"], cwd=target)
    else:
        _run(["git", "clone", "--mirror", url, str(target)])

    return target


def is_git_mirror_dir(path: Path) -> bool:
    """
    Heuristic to detect a mirror dir: ends with .git and has typical files.
    """
    return (
        path.is_dir()
        and path.name.endswith(".git")
        and (path / "config").exists()
        and (path / "HEAD").exists()
    )


def iter_mirrored_repos(base_dir: Path) -> Iterator[Path]:
    """
    Yield all mirror directories under base_dir recursively.
    """
    if not base_dir.exists():
        return
    for p in base_dir.rglob("*.git"):
        if is_git_mirror_dir(p):
            yield p


def fetch_mirror(repo_dir: Path) -> None:
    """
    Fetch updates for a single mirror repository.
    """
    _run(["git", "remote", "update", "--prune"], cwd=repo_dir)


def fetch_all(base_dir: Path) -> List[Tuple[Path, Optional[str]]]:
    """
    Iterate all mirrored repos under base_dir and fetch updates.
    Returns a list of tuples: (repo_path, error_message_or_None).
    """
    results: List[Tuple[Path, Optional[str]]] = []
    for repo in iter_mirrored_repos(base_dir):
        try:
            fetch_mirror(repo)
            results.append((repo, None))
        except subprocess.CalledProcessError as e:
            # Capture stderr for diagnostics, but keep going
            err = e.stderr.strip() if e.stderr else str(e)
            results.append((repo, err))
    return results


SYNC_MARKER = ".last_sync"


def record_sync_time(base_dir: Path) -> None:
    base_dir = base_dir.resolve()
    base_dir.mkdir(parents=True, exist_ok=True)
    marker = base_dir / SYNC_MARKER
    marker.write_text(datetime.utcnow().isoformat() + "\n", encoding="utf-8")


def read_sync_time(base_dir: Path) -> Optional[str]:
    marker = base_dir / SYNC_MARKER
    if marker.exists():
        return marker.read_text(encoding="utf-8").strip()
    return None
