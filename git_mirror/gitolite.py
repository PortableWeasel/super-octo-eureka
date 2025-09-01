#!/usr/bin/env python3
"""
Helpers to add mirrored repositories to a Gitolite configuration.

Strategy:
- Keep all mirror ACLs in conf/mirrors.conf, included from conf/gitolite.conf.
- Each repo gets an explicit read-only stanza, e.g.:

    repo mirrors/github.com/psf/requests.git
        R   = @all
        RW+ =

You can choose a different readers group.

Typical flow:
    ensure_admin_repo(admin_url, admin_dir)
    ensure_include_of_mirrors_conf(admin_dir)
    upsert_mirror_repo(admin_dir, "mirrors/github.com/psf/requests.git", readers="@all")
    commit_and_push(admin_dir, "Add mirror: mirrors/github.com/psf/requests.git")

You can build the repo path from a URL with git_mirror.core.parse_repo_id + gitolite_path_for.
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import subprocess
import re
from typing import Optional, List, Tuple, Dict, Any
import os

from .core import RepoID, parse_repo_id, iter_mirrored_repos, read_sync_time


def _run_git(args, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def ensure_admin_repo(admin_url: str, admin_dir: Path) -> Path:
    """
    Ensure a local clone of gitolite-admin exists at admin_dir.
    If it exists, fetch & reset to origin/master (or main).
    Returns the path.
    """
    admin_dir = admin_dir.resolve()
    if not admin_dir.exists():
        admin_dir.parent.mkdir(parents=True, exist_ok=True)
        _run_git(["clone", admin_url, str(admin_dir)], cwd=admin_dir.parent)
    # Refresh
    _run_git(["fetch", "--prune", "origin"], cwd=admin_dir)
    # Try both master and main because the world is inconsistent
    for branch in ("master", "main"):
        try:
            _run_git(["rev-parse", "--verify", f"origin/{branch}"], cwd=admin_dir)
            _run_git(["checkout", "-B", branch, f"origin/{branch}"], cwd=admin_dir)
            break
        except subprocess.CalledProcessError:
            continue
    return admin_dir


def ensure_include_of_mirrors_conf(admin_dir: Path, include_file: str = "mirrors.conf") -> Path:
    """
    Ensure conf/gitolite.conf includes `include "<include_file>"`.
    Creates conf/<include_file> if missing.
    """
    conf_dir = admin_dir / "conf"
    conf_dir.mkdir(parents=True, exist_ok=True)
    main_conf = conf_dir / "gitolite.conf"
    mirrors_conf = conf_dir / include_file

    if not main_conf.exists():
        raise FileNotFoundError(f"{main_conf} not found. Is this a gitolite-admin repo?")

    include_line = f'include "{include_file}"'
    text = main_conf.read_text(encoding="utf-8")

    if include_line not in text:
        # add include near the end, on its own line
        if not text.endswith("\n"):
            text += "\n"
        text += include_line + "\n"
        main_conf.write_text(text, encoding="utf-8")

    if not mirrors_conf.exists():
        mirrors_conf.write_text("# Managed by git_mirror.gitolite\n", encoding="utf-8")

    return mirrors_conf


def gitolite_path_for(rid: RepoID, prefix: str = "mirrors") -> str:
    """
    Build the Gitolite-visible path for a mirror (matches on-disk layout).
    Example: mirrors/github.com/psf/requests.git
    """
    return f"{prefix}/{rid.host}/{rid.owner}/{rid.name}.git"


@dataclass
class UpsertResult:
    path: str
    changed: bool
    file: Path


_STANZA_HEADER_RE = re.compile(r'^\s*repo\s+(.+?)\s*$', re.IGNORECASE)
_READER_LINE_RE = re.compile(r'^\s*R\s*=\s*(.+?)\s*$', re.IGNORECASE)


def upsert_mirror_repo(
    admin_dir: Path,
    repo_path: str,
    readers: str = "@all",
    mirrors_conf_file: str = "mirrors.conf",
) -> UpsertResult:
    """
    Ensure a read-only stanza for `repo_path` exists in conf/<mirrors_conf_file>.
    Returns UpsertResult(changed=bool).
    """
    mirrors_conf = admin_dir / "conf" / mirrors_conf_file
    if not mirrors_conf.exists():
        raise FileNotFoundError(f"{mirrors_conf} does not exist; call ensure_include_of_mirrors_conf first.")

    content = mirrors_conf.read_text(encoding="utf-8").splitlines()

    # Find existing stanza indices if present
    i = 0
    start_idx = end_idx = None
    while i < len(content):
        m = _STANZA_HEADER_RE.match(content[i])
        if m:
            current_repo = m.group(1).strip()
            # stanza ends before next 'repo ' header or file end
            j = i + 1
            while j < len(content) and not _STANZA_HEADER_RE.match(content[j]):
                j += 1
            if current_repo == repo_path:
                start_idx, end_idx = i, j
                break
            i = j
        else:
            i += 1

    desired = [
        f"repo {repo_path}",
        f"    R   = {readers}",
        "    RW+ =",
        "",
    ]

    if start_idx is None:
        # Append new stanza
        if content and content[-1].strip() != "":
            content.append("")  # ensure blank line before new stanza
        content.extend(desired)
        mirrors_conf.write_text("\n".join(content) + "\n", encoding="utf-8")
        return UpsertResult(path=repo_path, changed=True, file=mirrors_conf)

    # Update existing stanza minimally: ensure readers line is correct and RW+ is empty
    stanza = content[start_idx:end_idx]
    updated = False

    # Ensure R line
    has_r = False
    for k, line in enumerate(stanza):
        if _READER_LINE_RE.match(line):
            has_r = True
            new_line = f"    R   = {readers}"
            if line.strip() != new_line.strip():
                stanza[k] = new_line
                updated = True
            break
    if not has_r:
        stanza.insert(1, f"    R   = {readers}")
        updated = True

    # Ensure RW+ present and empty
    if not any(l.strip().lower().startswith("rw+") for l in stanza):
        stanza.insert(2, "    RW+ =")
        updated = True
    else:
        stanza = [
            ("    RW+ =" if l.strip().lower().startswith("rw+") else l)
            for l in stanza
        ]

    if updated:
        # write back merged content
        content = content[:start_idx] + stanza + content[end_idx:]
        mirrors_conf.write_text("\n".join(content) + "\n", encoding="utf-8")

    return UpsertResult(path=repo_path, changed=updated, file=mirrors_conf)


def commit_and_push(admin_dir: Path, message: str) -> None:
    """
    Commit any pending changes in the admin repo and push.
    No-op if there are no changes.
    """
    # Stage everything under conf/
    _run_git(["add", "conf"], cwd=admin_dir)

    # If nothing to commit, short-circuit
    status = _run_git(["status", "--porcelain"], cwd=admin_dir).stdout.strip()
    if not status:
        return

    _run_git(["commit", "-m", message], cwd=admin_dir)
    _run_git(["push", "origin", "HEAD"], cwd=admin_dir)


def add_url_to_gitolite(
    url: str,
    admin_url: str,
    admin_dir: Path,
    *,
    readers: str = "@all",
    prefix: str = "mirrors",
    mirrors_conf_file: str = "mirrors.conf",
) -> UpsertResult:
    """
    One-shot convenience: given an upstream URL, add its mirror path to Gitolite config.
    - Clones/refreshes gitolite-admin
    - Ensures include of mirrors.conf
    - Upserts the repo stanza
    - Commits and pushes (only if changes)
    """
    rid = parse_repo_id(url)
    repo_path = gitolite_path_for(rid, prefix=prefix)

    ensure_admin_repo(admin_url, admin_dir)
    ensure_include_of_mirrors_conf(admin_dir, include_file=mirrors_conf_file)
    res = upsert_mirror_repo(admin_dir, repo_path, readers=readers, mirrors_conf_file=mirrors_conf_file)
    if res.changed:
        commit_and_push(admin_dir, f"Add mirror: {repo_path}")
    return res


# ---------- helpers to read/write mirrors.conf ----------

def _mirrors_conf_path(admin_dir: Path, mirrors_conf_file: str) -> Path:
    p = admin_dir / "conf" / mirrors_conf_file
    if not p.exists():
        raise FileNotFoundError(f"{p} does not exist; run ensure_include_of_mirrors_conf() first.")
    return p


def parse_mirrors_conf(admin_dir: Path, mirrors_conf_file: str = "mirrors.conf") -> Dict[str, Tuple[int, int]]:
    """
    Parse conf/<mirrors_conf_file> and return a map:
        repo_path -> (start_index, end_index)
    Indices are line ranges [start, end) for the stanza.
    """
    mirrors_conf = _mirrors_conf_path(admin_dir, mirrors_conf_file)
    lines = mirrors_conf.read_text(encoding="utf-8").splitlines()
    pos: Dict[str, Tuple[int, int]] = {}

    i = 0
    while i < len(lines):
        m = _STANZA_HEADER_RE.match(lines[i])
        if not m:
            i += 1
            continue
        repo = m.group(1).strip()
        j = i + 1
        while j < len(lines) and not _STANZA_HEADER_RE.match(lines[j]):
            j += 1
        pos[repo] = (i, j)
        i = j
    return pos


def configured_mirror_paths(admin_dir: Path, mirrors_conf_file: str = "mirrors.conf") -> List[str]:
    """
    Return a list of 'repo <path>' entries currently configured in mirrors.conf.
    """
    return sorted(parse_mirrors_conf(admin_dir, mirrors_conf_file).keys())


def gitolite_path_from_mirror_dir(base_dir: Path, repo_dir: Path, prefix: str = "mirrors") -> str:
    """
    Convert an on-disk mirror path into the Gitolite path.
    Example:
        base_dir=/home/git/repositories/mirrors
        repo_dir=/home/git/repositories/mirrors/github.com/psf/requests.git
        -> mirrors/github.com/psf/requests.git
    """
    base_dir = base_dir.resolve()
    repo_dir = repo_dir.resolve()
    rel = repo_dir.relative_to(base_dir)  # raises if not under base_dir
    # Ensure .git suffix is present in the Gitolite path
    name = rel.name if rel.name.endswith(".git") else f"{rel.name}.git"
    rel = rel.with_name(name)
    return str(Path(prefix) / rel)


def sync_gitolite_from_disk(
    base_dir: Path,
    admin_url: str,
    admin_dir: Path,
    *,
    readers: str = "@all",
    prefix: str = "mirrors",
    mirrors_conf_file: str = "mirrors.conf",
    prune: bool = False,
) -> Tuple[List[str], List[str]]:
    """
    Ensure every on-disk mirror under base_dir has a corresponding read-only
    entry in gitolite's mirrors.conf. Optionally prune stanzas whose mirrors
    no longer exist on disk.

    Returns (added_paths, pruned_paths).
    """
    ensure_admin_repo(admin_url, admin_dir)
    ensure_include_of_mirrors_conf(admin_dir, include_file=mirrors_conf_file)

    # Build sets
    disk_paths: List[str] = []
    for repo in iter_mirrored_repos(base_dir):
        try:
            disk_paths.append(gitolite_path_from_mirror_dir(base_dir, repo, prefix=prefix))
        except Exception:
            # Skip anything weird that's not under base_dir
            continue
    set_disk = set(disk_paths)
    set_cfg = set(configured_mirror_paths(admin_dir, mirrors_conf_file))

    to_add = sorted(set_disk - set_cfg)
    to_prune = sorted(set_cfg - set_disk) if prune else []

    # Add missing
    changed = False
    added: List[str] = []
    for path in to_add:
        res = upsert_mirror_repo(admin_dir, path, readers=readers, mirrors_conf_file=mirrors_conf_file)
        if res.changed:
            changed = True
        added.append(path)

    # Prune stale stanzas
    pruned: List[str] = []
    if to_prune:
        mirrors_conf = _mirrors_conf_path(admin_dir, mirrors_conf_file)
        lines = mirrors_conf.read_text(encoding="utf-8").splitlines()
        spans = parse_mirrors_conf(admin_dir, mirrors_conf_file)

        # Remove from bottom to top so indices stay valid
        for repo in sorted(to_prune, key=lambda r: spans[r][0], reverse=True):
            si, sj = spans[repo]
            del lines[si:sj]
            # Trim surrounding blank lines
            while si < len(lines) and lines[si].strip() == "":
                del lines[si]
            changed = True
            pruned.append(repo)

        mirrors_conf.write_text("\n".join(lines) + ("\n" if lines and lines[-1] != "" else ""), encoding="utf-8")

    if changed:
        commit_and_push(admin_dir, "Sync mirrors.conf with on-disk mirrors")

    return added, pruned


def status_report(
    base_dir: Path,
    admin_url: str,
    admin_dir: Path,
    *,
    prefix: str = "mirrors",
    mirrors_conf_file: str = "mirrors.conf",
) -> Dict[str, Any]:
    """Return a summary of mirror status versus gitolite configuration."""
    ensure_admin_repo(admin_url, admin_dir)
    ensure_include_of_mirrors_conf(admin_dir, include_file=mirrors_conf_file)

    disk_paths: List[str] = []
    bad_layout: List[str] = []
    for repo in iter_mirrored_repos(base_dir):
        try:
            disk_paths.append(
                gitolite_path_from_mirror_dir(base_dir, repo, prefix=prefix)
            )
        except Exception:
            bad_layout.append(str(repo))

    set_disk = set(disk_paths)
    set_cfg = set(configured_mirror_paths(admin_dir, mirrors_conf_file))

    return {
        "bad_layout": sorted(bad_layout),
        "missing_in_config": sorted(set_disk - set_cfg),
        "missing_on_disk": sorted(set_cfg - set_disk),
        "last_sync": read_sync_time(base_dir),
    }
