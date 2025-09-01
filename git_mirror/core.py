#!/usr/bin/env python3
"""
Core utilities for mirroring Git repositories into a GitHub-like folder layout.

Layout:
  <base_dir>/<host>/<owner_or_org>/<repo>.git

Examples:
  https://github.com/numpy/numpy.git  -> base/github.com/numpy/numpy.git
  git@github.com:torvalds/linux.git   -> base/github.com/torvalds/linux.git
  https://gitlab.com/group/sub/repo   -> base/gitlab.com/group/repo.git

Notes:
- For multi-segment namespaces (e.g. GitLab subgroups), we keep only the first
  segment as the "owner" and the final segment as the repo, to match the
  requested "user-or-org/repo" pattern.
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
    owner: str
    name: str  # repo name without trailing .git

    def mirror_dir(self, base_dir: Path) -> Path:
        return base_dir / self.host / self.owner / f"{self.name}.git"


def _strip_git_suffix(repo: str) -> str:
    return repo[:-4] if repo.endswith(".git") else repo


def _parse_ssh_like(url: str) -> Optional[Tuple[str, str]]:
    """
    Parse git@host:owner/repo(.git)? into (host, path)
    """
    m = SSH_SCHEME_RE.match(url)
    if not m:
        return None
    return m.group("host"), m.group("path")


def _split_owner_and_repo(path: str) -> Tuple[str, str]:
    """
    Convert a path like:
      owner/repo
      owner/sub/repo
      /owner/repo.git
    into ("owner", "repo") by taking the first and last components.
    """
    parts = [p for p in Path(path).parts if p not in ("/", "")]

    # Drop common VCS prefixes if someone passes paths like "scm/repo"
    # but we keep this minimal; the primary rule is first and last segment.
    if len(parts) == 0:
        raise ValueError(f"Cannot parse owner/repo from empty path: {path}")

    owner = parts[0]
    repo = _strip_git_suffix(parts[-1])
    if repo in ("", ".", ".."):
        raise ValueError(f"Suspicious repo segment parsed from path: {path}")
    return owner, repo


def parse_repo_id(url: str) -> RepoID:
    """
    Parse a Git URL (ssh-like or http(s)) into RepoID(host, owner, name).
    """
    # SSH style: git@host:owner/repo(.git)
    ssh = _parse_ssh_like(url)
    if ssh is not None:
        host, path = ssh
        owner, repo = _split_owner_and_repo(path)
        return RepoID(host=host, owner=owner, name=repo)

    # HTTP(S) style
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https", "ssh", "git"):
        host = parsed.hostname or ""
        if not host:
            raise ValueError(f"Missing host in URL: {url}")
        # parsed.path starts with '/', remove it for clean splitting
        owner, repo = _split_owner_and_repo(parsed.path.lstrip("/"))
        return RepoID(host=host, owner=owner, name=repo)

    # Local path fallback (less common for your use case, but harmless)
    if os.path.exists(url):
        # Treat local path as /owner/repo(.git), where owner is parent folder name
        p = Path(url).resolve()
        if p.is_dir() and p.name.endswith(".git"):
            repo = _strip_git_suffix(p.name)
            owner = p.parent.name or "_local"
            return RepoID(host="_local", owner=owner, name=repo)
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
    Ensure a repository is mirror-cloned under base_dir in host/owner/repo.git.
    If already present, do a remote update; if not, perform `git clone --mirror`.
    Returns the path to the mirror directory.
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
