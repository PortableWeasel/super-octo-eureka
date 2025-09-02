# super-octo-eureka

Git repo mirroring command line utility.

## Features

- Mirror-clone repositories into a GitHub-like directory tree using `git clone --mirror`.
- Update all mirrored repositories with a single command.
- Integrate with Gitolite by adding and syncing mirror entries in `gitolite-admin`.
- Mirror submodule repositories recursively.

## Command line usage

Invoke the CLI via the module:

```bash
python -m git_mirror.cli --help
```

### `clone`
Mirror-clone (or update) a single repository. Pass `--with-submodules` to
mirror any submodule repositories as well.

```
python -m git_mirror.cli clone <url> --base-dir <path> [--with-submodules]
```
Example:

```bash
python -m git_mirror.cli clone https://github.com/psf/requests.git --base-dir /srv/git --with-submodules
```

### `update-all`
Fetch updates for every mirror under `--base-dir` and record the last sync time.

```
python -m git_mirror.cli update-all --base-dir <path>
```
Example:

```bash
python -m git_mirror.cli update-all --base-dir /srv/git
```

### `list`
List all detected mirror repositories.

```
python -m git_mirror.cli list --base-dir <path>
```

### `mirror-submodules`
Mirror any submodule repositories referenced by existing mirrors.

```
python -m git_mirror.cli mirror-submodules --base-dir <path>
```
Example:

```bash
python -m git_mirror.cli mirror-submodules --base-dir /srv/git
```

### `gitolite-add`
Add or update a mirror entry in `gitolite-admin`.

```
python -m git_mirror.cli gitolite-add <url> --admin-url <ssh-url> --admin-dir <path> [--readers @all] [--prefix mirrors] [--conf-file mirrors.conf]
```
Example:

```bash
python -m git_mirror.cli gitolite-add https://github.com/psf/requests.git \
  --admin-url git@yourhost:gitolite-admin \
  --admin-dir /home/git/gitolite-admin
```

### `gitolite-sync`
Ensure the Gitolite configuration matches on-disk mirrors. Pass `--prune` to remove stale entries.

```
python -m git_mirror.cli gitolite-sync --base-dir <path> --admin-url <ssh-url> --admin-dir <path> [--readers @all] [--prefix mirrors] [--conf-file mirrors.conf] [--prune]
```
Example:

```bash
python -m git_mirror.cli gitolite-sync --base-dir /srv/git \
  --admin-url git@yourhost:gitolite-admin \
  --admin-dir /home/git/gitolite-admin
```

### `status`
Report on the state of mirror folders and Gitolite configuration. Shows layout problems, mirrors missing from the config, config entries without a mirror, and the last recorded sync time.

```
python -m git_mirror.cli status --base-dir <path> --admin-url <ssh-url> --admin-dir <path> [--prefix mirrors] [--conf-file mirrors.conf]
```
Example:

```bash
python -m git_mirror.cli status --base-dir /srv/git \
  --admin-url git@yourhost:gitolite-admin \
  --admin-dir /home/git/gitolite-admin
```

### `completion`
Generate a shell completion script for Bash or Zsh. Evaluate the output to enable
tab completion in the current shell session.

```
python -m git_mirror.cli completion [--prog git-mirror]
```
Example:

```bash
eval "$(python -m git_mirror.cli completion)"
```
Requires `argcomplete` to be installed.

## System integration

Example systemd units are provided in `examples/systemd`.
Install and enable them with:

```bash
sudo cp examples/systemd/git-mirror.service /etc/systemd/system/
sudo cp examples/systemd/git-mirror.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now git-mirror.timer
```

To install a user-level systemd timer instead, run:

```bash
python -m git_mirror.cli register-service --base-dir /home/git/repositories/mirrors
```

If `--base-dir` is omitted, the current directory is used when it contains `.git-mirror.conf`.

## Gitolite configuration

Sample Gitolite configuration files live in `examples/gitolite`.
`gitolite.conf` must include `mirrors.conf`, and each mirror should
have a read-only stanza:

```conf
repo mirrors/github.com/psf/requests.git
    R   = @all
    RW+ =
```

Install Gitolite on Debian/Ubuntu systems with:

```bash
sudo apt install gitolite3
```

After mirroring repositories, run the sync command above to keep
`mirrors.conf` in line with on-disk mirrors.
