#!/usr/bin/env python3
"""
CLI for git_mirror.

Commands:
  clone  <url> --base-dir /path      Mirror-clone (or update) a single repo
  update-all --base-dir /path        Fetch all mirrors under base-dir
  list       --base-dir /path        List detected mirrors
  gitolite-add <url> ...             Add a mirror to gitolite config
  gitolite-sync --base-dir ...       Sync gitolite config with on-disk mirrors

Examples:
  git-mirror clone https://github.com/psf/requests.git --base-dir /srv/git
  git-mirror update-all --base-dir /srv/git
"""

from __future__ import annotations
import argparse
from pathlib import Path

from .core import ensure_mirror, fetch_all, iter_mirrored_repos, record_sync_time
from .gitolite import add_url_to_gitolite, sync_gitolite_from_disk, status_report


def cmd_clone(args: argparse.Namespace) -> int:
    target = ensure_mirror(args.url, Path(args.base_dir))
    print(str(target))
    return 0


def cmd_update_all(args: argparse.Namespace) -> int:
    results = fetch_all(Path(args.base_dir))
    failed = [r for r in results if r[1]]
    for repo, err in results:
        if err:
            print(f"[FAIL] {repo} :: {err}")
        else:
            print(f"[OK]   {repo}")
    record_sync_time(Path(args.base_dir))
    return 1 if failed else 0


def cmd_list(args: argparse.Namespace) -> int:
    base = Path(args.base_dir)
    for repo in iter_mirrored_repos(base):
        print(str(repo))
    return 0


def cmd_gitolite_add(args: argparse.Namespace) -> int:
    res = add_url_to_gitolite(
        url=args.url,
        admin_url=args.admin_url,
        admin_dir=Path(args.admin_dir),
        readers=args.readers,
        prefix=args.prefix,
        mirrors_conf_file=args.conf_file,
    )
    print(f"{'UPDATED' if res.changed else 'UNCHANGED'} {res.path} in {res.file}")
    return 0


def cmd_gitolite_sync(args: argparse.Namespace) -> int:
    added, pruned = sync_gitolite_from_disk(
        base_dir=Path(args.base_dir),
        admin_url=args.admin_url,
        admin_dir=Path(args.admin_dir),
        readers=args.readers,
        prefix=args.prefix,
        mirrors_conf_file=args.conf_file,
        prune=bool(args.prune),
    )
    for p in added:
        print(f"[ADDED] {p}")
    for p in pruned:
        print(f"[PRUNED] {p}")
    if not added and not pruned:
        print("[OK] mirrors.conf already in sync")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    report = status_report(
        base_dir=Path(args.base_dir),
        admin_url=args.admin_url,
        admin_dir=Path(args.admin_dir),
        prefix=args.prefix,
        mirrors_conf_file=args.conf_file,
    )
    print(f"Last sync: {report['last_sync'] or 'never'}")
    for p in report["bad_layout"]:
        print(f"[BAD LAYOUT] {p}")
    for p in report["missing_in_config"]:
        print(f"[UNCONFIGURED] {p}")
    for p in report["missing_on_disk"]:
        print(f"[MISSING] {p}")
    if (
        not report["bad_layout"]
        and not report["missing_in_config"]
        and not report["missing_on_disk"]
    ):
        print("[OK] mirrors and config in sync")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="git-mirror", description="Mirror-clone and update Git repositories in a GitHub-like layout.")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_clone = sub.add_parser("clone", help="Mirror-clone or update a single URL")
    p_clone.add_argument("url", help="Git URL (ssh or https)")
    p_clone.add_argument("--base-dir", required=True, help="Base directory for mirrors")
    p_clone.set_defaults(func=cmd_clone)

    p_update = sub.add_parser("update-all", help="Fetch updates for all mirrors")
    p_update.add_argument("--base-dir", required=True, help="Base directory for mirrors")
    p_update.set_defaults(func=cmd_update_all)

    p_list = sub.add_parser("list", help="List detected mirror repositories")
    p_list.add_argument("--base-dir", required=True, help="Base directory for mirrors")
    p_list.set_defaults(func=cmd_list)

    p_gitolite = sub.add_parser("gitolite-add", help="Add a mirror repo ACL to gitolite-admin")
    p_gitolite.add_argument("url", help="Upstream Git URL (ssh or https)")
    p_gitolite.add_argument("--admin-url", required=True, help="gitolite-admin repo URL (ssh)")
    p_gitolite.add_argument("--admin-dir", required=True, help="Local path for gitolite-admin checkout")
    p_gitolite.add_argument("--readers", default="@all", help="Readers group or user list (default: @all)")
    p_gitolite.add_argument("--prefix", default="mirrors", help="Path prefix inside gitolite (default: mirrors)")
    p_gitolite.add_argument("--conf-file", default="mirrors.conf", help="Included conf filename (default: mirrors.conf)")
    p_gitolite.set_defaults(func=cmd_gitolite_add)

    p_sync = sub.add_parser("gitolite-sync", help="Ensure gitolite mirrors.conf matches on-disk mirrors")
    p_sync.add_argument("--base-dir", required=True, help="Root folder of mirrors on disk (e.g., ~git/repositories/mirrors)")
    p_sync.add_argument("--admin-url", required=True, help="gitolite-admin repo URL (ssh)")
    p_sync.add_argument("--admin-dir", required=True, help="Local path to gitolite-admin checkout")
    p_sync.add_argument("--readers", default="@all", help="Readers group or list to apply for new entries")
    p_sync.add_argument("--prefix", default="mirrors", help="Gitolite path prefix (default: mirrors)")
    p_sync.add_argument("--conf-file", default="mirrors.conf", help="Included conf filename (default: mirrors.conf)")
    p_sync.add_argument("--prune", action="store_true", help="Remove config entries whose mirrors are gone on disk")
    p_sync.set_defaults(func=cmd_gitolite_sync)

    p_status = sub.add_parser("status", help="Report mirrors vs gitolite config")
    p_status.add_argument("--base-dir", required=True, help="Root folder of mirrors on disk")
    p_status.add_argument("--admin-url", required=True, help="gitolite-admin repo URL (ssh)")
    p_status.add_argument("--admin-dir", required=True, help="Local path to gitolite-admin checkout")
    p_status.add_argument("--prefix", default="mirrors", help="Gitolite path prefix (default: mirrors)")
    p_status.add_argument("--conf-file", default="mirrors.conf", help="Included conf filename (default: mirrors.conf)")
    p_status.set_defaults(func=cmd_status)

    return p


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
