
You said:
What are some utilities I could use to host a git server that periodically fetches updates from upstream projects?
ChatGPT said:
So you want your own little Git butler that not only stores code but also goes jogging upstream every so often to fetch updates. Perfectly doable. Here are a few ways you can set it up, depending on how much control and pain you’re willing to tolerate:
1. Plain Git + Cron Jobs
Host a bare repo on your server.
Set up a cron job or systemd timer that runs git fetch upstream on a schedule.
Dead simple, but you’ll be doing the automation duct-taping yourself.
Pros: zero new tools.
Cons: you’re the sysadmin, janitor, and babysitter.
2. Gitolite
Old-school but solid. Gitolite handles access control and hosting.
You can script periodic fetches with hooks or cron jobs.
Great if you want fine-grained permissions but don’t need flashy web UIs.
3. Gitea / Forgejo
Lightweight GitHub/GitLab lookalike, runs on a potato.
Has built-in mirroring and sync features (can periodically pull from upstream).
Friendly web interface, easy user management, CI/CD hooks if you want to overcomplicate things.
4. GitLab (Self-Hosted)
The big tank: web UI, CI/CD, issue tracking, kitchen sink.
Can set up repository mirrors to fetch from upstream automatically.
More resources and maintenance overhead than Gitea, but if you want the full corporate GitHub fantasy, it’s all there.
5. git-sync
Tiny sidecar/container utility that keeps a repo in sync with an upstream.
Originally from Kubernetes land, but works anywhere you want a dumb sync loop.
If you just need “this repo, but updated regularly,” this is the lean option.
6. Repo Mirroring with Hooks
Git itself has post-update hooks.
You can wire a hook to fetch from upstream after pushes, or to regularly sync.
Not as clean as a dedicated mirror feature, but free.
If you want minimal fuss: use Gitea/Forgejo. They literally have a checkbox for “mirror this repo from upstream every X minutes.”
If you want bare-metal simplicity: Git + cron. It’s the duct tape solution that never dies.
Do you want me to sketch out how to wire up the cron-job version so you can start with the least possible ceremony?

You said:
Yes, I'll configure gitolite to handle remote access, and I'd like to write a python utility that will handle cloning upstream repos to a local folder, that uses 'user or org name/project name' like GitHub does. The repos should be cloned using the '--mirror' flag

I'll use a systemd service on a timer unit to check for updates, by iterating through all git repos detected in the local folders

Could you please write the appropriate python modules that will

Given a url, mirror clone the repo to a folder with a similar path structure to what GitHub uses

Provide a function that iterates through all of the cloned repos in the local folder mirrored got repos

Have a function that uses this iteration to call git fetch on all of these repos
ChatGPT said:

Thought for 14s
Got it. You’ll use Gitolite for access, and a Python tool to mirror-clone by URL into a GitHub-ish layout, then a timer-driven sweep to fetch updates. Here’s a small, boringly reliable package that does exactly that. No yak shaving required.
I’m giving you a tidy module split plus a CLI so your systemd unit can just call git-mirror update-all.

git_mirror/core.py
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
git_mirror/cli.py
#!/usr/bin/env python3
"""
CLI for git_mirror.

Commands:
  clone  <url> --base-dir /path      Mirror-clone (or update) a single repo
  update-all --base-dir /path        Fetch all mirrors under base-dir
  list       --base-dir /path        List detected mirrors

Examples:
  git-mirror clone https://github.com/psf/requests.git --base-dir /srv/git
  git-mirror update-all --base-dir /srv/git
"""

from __future__ import annotations
import argparse
from pathlib import Path
from .core import ensure_mirror, fetch_all, iter_mirrored_repos


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
    return 1 if failed else 0


def cmd_list(args: argparse.Namespace) -> int:
    base = Path(args.base_dir)
    for repo in iter_mirrored_repos(base):
        print(str(repo))
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

    return p


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
git_mirror/__init__.py
from .core import (
    RepoID,
    parse_repo_id,
    ensure_mirror,
    iter_mirrored_repos,
    fetch_mirror,
    fetch_all,
)
Install locally
# Put these files in a package folder:
#   git_mirror/__init__.py
#   git_mirror/core.py
#   git_mirror/cli.py
#
# Then either:
python -m git_mirror.cli --help

# Or add a console script via pyproject if you’re feeling civilized:
# [project.scripts]
# git-mirror = "git_mirror.cli:main"
Systemd units
You didn’t ask, but you’re clearly going to do this anyway, so here:
/etc/systemd/system/git-mirror.service

[Unit]
Description=Update all mirrored git repositories

[Service]
Type=oneshot
User=git
Group=git
ExecStart=/usr/bin/env python3 -m git_mirror.cli update-all --base-dir /srv/git
WorkingDirectory=/srv/git
/etc/systemd/system/git-mirror.timer
[Unit]
Description=Run git mirror updates periodically

[Timer]
OnBootSec=2m
OnUnitActiveSec=15m
RandomizedDelaySec=60s
Unit=git-mirror.service

[Install]
WantedBy=timers.target
Enable:
sudo systemctl daemon-reload
sudo systemctl enable --now git-mirror.timer
Quick sanity checks
# Mirror-clone a repo
python -m git_mirror.cli clone https://github.com/psf/requests.git --base-dir /srv/git
# -> /srv/git/github.com/psf/requests.git

# List mirrors
python -m git_mirror.cli list --base-dir /srv/git

# Update all mirrors
python -m git_mirror.cli update-all --base-dir /srv/git
If you want stricter namespace behavior for non-GitHub hosts, tweak _split_owner_and_repo to enforce exactly two segments and fail otherwise. But for mixed ecosystems (GitHub, GitLab with subgroups), the current “first segment as owner, last as repo” gives the GitHub-style shape you asked for without making your life annoying. You’re welcome.
You said:
You are amazing 🤩

What would it take to make this whole set up place nice with gitolite?
ChatGPT said:

Thought for 19s
You’ve already built the mirror robot. Now you want it to wear a Gitolite uniform and salute on command. Fine. Here’s the clean way to make your Python mirrors and Gitolite coexist without stepping on each other’s toes.
The short version
Put your mirrors inside Gitolite’s repo base (usually ~git/repositories), under a prefix like mirrors/.
Name them using your “host/owner/repo.git” layout.
Add a wildcard repo rule in gitolite.conf that grants read-only access to anything under mirrors/.
Run your systemd timer as the gitolite user so ownership and perms don’t go feral.
Users clone like: git@yourhost:mirrors/github.com/psf/requests.git
That’s it. Your Python tool keeps them up-to-date; Gitolite handles access control like the bouncer it is.
Directory layout that Gitolite expects
Gitolite keeps repos under something like:
~git/
  repositories/
    gitolite-admin.git
    mirrors/
      github.com/
        psf/
          requests.git/
      gitlab.com/
        foo/
          bar.git/
Use that path as your --base-dir for the Python tool:
--base-dir ~git/repositories/mirrors
The tool will create the host/owner/repo.git tree under mirrors/, which Gitolite will happily serve as long as the names are whitelisted in the config.
Gitolite config: one wildcard to rule them all
Open gitolite-admin and edit conf/gitolite.conf:
# groups are optional but keep things civilized
@readers   = @all           # or a smaller group if you don’t want world-readable
@admins    = git-admins     # whoever can touch config

# Wildcard rule for everything under "mirrors/"
# Gitolite v3 treats "foo/..*" as a wildcard prefix.
repo mirrors/..*
    R     = @readers        # read-only for readers
    RW+   =                 # nobody gets write
    # Optional niceties:
    config gitweb.owner         = "Mirrors"
    config gitweb.description   = "Upstream mirrors, read-only"
    config http.receivepack     = false
    config http.uploadpack      = true
Commit and push back to gitolite-admin. No need to enumerate each repo; your one wildcard covers all future mirrors your Python script creates.
Users can now:

git clone git@yourhost:mirrors/github.com/psf/requests.git
If you’re using cgit or gitweb, those config lines help populate metadata. Not required, just classy.
Permissions and ownership
Make sure the mirror directories are owned by the gitolite user, or Gitolite will pout.
sudo -u git mkdir -p ~git/repositories/mirrors
sudo chown -R git:git ~git/repositories/mirrors
Run your systemd service/timer as User=git and Group=git, with:
ExecStart=/usr/bin/env python3 -m git_mirror.cli update-all --base-dir /home/git/repositories/mirrors
WorkingDirectory=/home/git
Yes, the path might be /var/lib/gitolite/repositories on your distro. You can read a config file or environment variable if you enjoy being fancy; otherwise hardcode and move on with your life.
Small tweak to your Python tool (optional but nice)
If you want the tool to print the Gitolite path a user should clone, add a helper:
# in core.py
def gitolite_path_for(rid: RepoID, prefix: str = "mirrors") -> str:
    return f"{prefix}/{rid.host}/{rid.owner}/{rid.name}.git"
And in cmd_clone, after ensure_mirror, also print:
print(f"gitolite path: {gitolite_path_for(parse_repo_id(args.url))}")
This gives you a copy-pasteable git@host:<that> string for docs or sanity checks.
Read-only guarantee (belt and suspenders)
Gitolite is already blocking writes via the ACL, but if you want your mirrors themselves to scream “do not push” even if someone bypasses Gitolite somehow:
git -C ~git/repositories/mirrors/github.com/psf/requests.git \
    config receive.denyAll true
You can also set that in your script right after cloning. Not required, just extra drama.
Hooks: what you don’t need
You do not need custom per-repo hooks just to serve reads over SSH.
You do not need update-server-info unless you’re doing dumb HTTP. Still harmless if you run it.
If you later expose these via HTTP(S) with the smart backend, make sure http.uploadpack is true (it is in the config snippet).
Systemd timer recap
Service:
[Unit]
Description=Update all mirrored git repositories

[Service]
Type=oneshot
User=git
Group=git
ExecStart=/usr/bin/env python3 -m git_mirror.cli update-all --base-dir /home/git/repositories/mirrors
WorkingDirectory=/home/git
Timer:
[Unit]
Description=Run git mirror updates periodically

[Timer]
OnBootSec=2m
OnUnitActiveSec=15m
RandomizedDelaySec=60s
Unit=git-mirror.service

[Install]
WantedBy=timers.target
Troubleshooting, because something will go weird
Permission denied when cloning from Gitolite
The repo exists on disk but Gitolite says no. Your wildcard is wrong or you pushed the wrong gitolite.conf. Run ssh git@yourhost info and see what repos it lists.
Gitolite shows stale refs after your updater runs
Not a thing with SSH, but for HTTP dumb mode you may need git update-server-info. Stick it after fetch if you go that route.
Users keep trying to push
They will. Your ACL already blocks it. If you want a friendlier error, put the word “mirror” in the path as we did. Humans read nouns better than error messages.
SELinux/AppArmor has Opinions
Then set your contexts or disable for the repo path. Not Gitolite’s fault; that’s your OS being overprotective, like a raccoon guarding garbage.
Bonus: mirroring private upstreams
If you mirror private upstreams over SSH:
Put the deploy key in ~git/.ssh/, lock perms to 0600.
Add known_hosts entries so your timer doesn’t stall on first contact.
Use SSH URLs in your mirror list; your Python tool doesn’t care.
That’s the whole dance. Your Python script keeps the mirrors current, Gitolite hands out read-only access like vending machine snacks, and nobody gets to push into the mirrors. Efficient, boring, reliable. Like good infrastructure should be.
You said:
Could you please add another python module to the existing code you've written, that will handle adding a new repo to the gitolite config automatically?
ChatGPT said:

Thought for 12s
Right, you want your mirroring bot to also whisper sweet nothings into Gitolite’s config. Here’s a clean add-on module that:
clones or reuses a local gitolite-admin checkout,
ensures your main config includes a managed file conf/mirrors.conf,
adds a read-only stanza for the new mirror path (e.g. repo mirrors/github.com/psf/requests.git),
commits and pushes.
I also wired a CLI subcommand so your timer or provisioning script can call it directly.
git_mirror/gitolite.py
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
from typing import Optional

from .core import RepoID, parse_repo_id  # reuse types


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
CLI update: add gitolite-add
Append this subcommand to your existing git_mirror/cli.py. Only the new bits are shown here; keep the rest as-is.
# add near the top
from .gitolite import add_url_to_gitolite

# inside _build_parser()
    p_gitolite = sub.add_parser("gitolite-add", help="Add a mirror repo ACL to gitolite-admin")
    p_gitolite.add_argument("url", help="Upstream Git URL (ssh or https)")
    p_gitolite.add_argument("--admin-url", required=True, help="gitolite-admin repo URL (ssh)")
    p_gitolite.add_argument("--admin-dir", required=True, help="Local path for gitolite-admin checkout")
    p_gitolite.add_argument("--readers", default="@all", help="Readers group or user list (default: @all)")
    p_gitolite.add_argument("--prefix", default="mirrors", help="Path prefix inside gitolite (default: mirrors)")
    p_gitolite.add_argument("--conf-file", default="mirrors.conf", help="Included conf filename (default: mirrors.conf)")
    p_gitolite.set_defaults(func=cmd_gitolite_add)

# add a new handler
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
And export the helper if you like:
# git_mirror/__init__.py
from .gitolite import (
    ensure_admin_repo,
    ensure_include_of_mirrors_conf,
    upsert_mirror_repo,
    commit_and_push,
    add_url_to_gitolite,
    gitolite_path_for,
)
Example usage
# 1) Mirror on disk (as before)
git-mirror clone https://github.com/psf/requests.git --base-dir /home/git/repositories/mirrors

# 2) Add to gitolite config
git-mirror gitolite-add https://github.com/psf/requests.git \
  --admin-url git@yourhost:gitolite-admin \
  --admin-dir /home/git/gitolite-admin \
  --readers @all \
  --prefix mirrors
That will:
create/update /home/git/gitolite-admin/conf/mirrors.conf,
ensure conf/gitolite.conf includes it,
add an entry:
repo mirrors/github.com/psf/requests.git
    R   = @all
    RW+ =
commit and push if anything changed.
Notes and sane defaults
Run this as the git user so credentials for git@yourhost:gitolite-admin Just Work.
You can swap @all for a smaller group like @readers if you’ve defined one.
If you already use a single wildcard rule for mirrors/..*, you technically don’t need per-repo stanzas. This module still plays nice: it creates explicit entries only for the repos you add, which some teams prefer for auditability.
There. Now your mirror script not only fetches code but also politely tells Gitolite about it, no manual config edits, no crying in vim.
You said:
Okay initially I was avoiding it, but I think I'll also need to be able to periodically run a check to make sure all the repos in the local folders have a corresponding entry in gitolite. Think you could handle that too?
ChatGPT said:

Thought for 7s
You want a compliance cop for your mirrors. Fine. I wrote you one that patrols the mirror directory, compares it to gitolite-admin, and adds any missing ACL stanzas. Optional pruning too, in case you enjoy deleting things on purpose.
Below are drop-in additions to what we already built.

git_mirror/gitolite.py (additions)
# ... keep existing imports and code at top of git_mirror/gitolite.py
from typing import List, Tuple, Dict
from .core import iter_mirrored_repos  # reuse walk
import os

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
git_mirror/cli.py (new subcommand)
# add near the top with other imports
from .gitolite import sync_gitolite_from_disk

# inside _build_parser()
    p_sync = sub.add_parser("gitolite-sync", help="Ensure gitolite mirrors.conf matches on-disk mirrors")
    p_sync.add_argument("--base-dir", required=True, help="Root folder of mirrors on disk (e.g., ~git/repositories/mirrors)")
    p_sync.add_argument("--admin-url", required=True, help="gitolite-admin repo URL (ssh)")
    p_sync.add_argument("--admin-dir", required=True, help="Local path to gitolite-admin checkout")
    p_sync.add_argument("--readers", default="@all", help="Readers group or list to apply for new entries")
    p_sync.add_argument("--prefix", default="mirrors", help="Gitolite path prefix (default: mirrors)")
    p_sync.add_argument("--conf-file", default="mirrors.conf", help="Included conf filename (default: mirrors.conf)")
    p_sync.add_argument("--prune", action="store_true", help="Remove config entries whose mirrors are gone on disk")
    p_sync.set_defaults(func=cmd_gitolite_sync)

# add the handler
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
And export it if you care:
# git_mirror/__init__.py
from .gitolite import sync_gitolite_from_disk, configured_mirror_paths, parse_mirrors_conf, gitolite_path_from_mirror_dir
How you actually use this, without summoning chaos
Your mirroring still runs as before:
git-mirror update-all --base-dir /home/git/repositories/mirrors
Then run the sync to enforce ACL coverage:
git-mirror gitolite-sync \
  --base-dir /home/git/repositories/mirrors \
  --admin-url git@yourhost:gitolite-admin \
  --admin-dir /home/git/gitolite-admin \
  --readers @all \
  --prefix mirrors
If you want to clean out stale config entries:
git-mirror gitolite-sync ... --prune
Wire both into a single systemd service or two separate ones. Example combined service:
[Unit]
Description=Mirror and sync Gitolite ACLs for upstream mirrors

[Service]
Type=oneshot
User=git
Group=git
WorkingDirectory=/home/git
ExecStart=/usr/bin/env python3 -m git_mirror.cli update-all --base-dir /home/git/repositories/mirrors
ExecStart=/usr/bin/env python3 -m git_mirror.cli gitolite-sync --base-dir /home/git/repositories/mirrors --admin-url git@yourhost:gitolite-admin --admin-dir /home/git/gitolite-admin --readers @all --prefix mirrors --conf-file mirrors.conf
Timer stays the same.
Edge cases this handles so you don’t have to
Multi-host mirrors: paths include github.com/..., gitlab.com/..., etc. No special logic needed.
Missing include line: it auto-adds include "mirrors.conf" to conf/gitolite.conf.
Conflicts or manual edits: if your stanza already exists, it’s updated to enforce R = <readers> and empty RW+.
Human error: if a repo folder gets deleted on disk, --prune removes its stanza to avoid ghost entries.
No magic, no YAML cults, just text files and a small, stubborn script that refuses to drift.