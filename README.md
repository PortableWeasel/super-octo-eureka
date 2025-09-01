# super-octo-eureka

Git repo mirroring command line utility.

## Features

- Mirror-clone repositories into a GitHub-like directory tree using `git clone --mirror`.
- Update all mirrored repositories with a single command.
- Integrate with Gitolite by adding and syncing mirror entries in `gitolite-admin`.

## Usage

Run the commands via the module:

```bash
python -m git_mirror.cli --help
```

To mirror a repository:

```bash
python -m git_mirror.cli clone https://github.com/psf/requests.git --base-dir /srv/git
```

To update all mirrors:

```bash
python -m git_mirror.cli update-all --base-dir /srv/git
```

To add the mirror to Gitolite:

```bash
python -m git_mirror.cli gitolite-add https://github.com/psf/requests.git \
  --admin-url git@yourhost:gitolite-admin \
  --admin-dir /home/git/gitolite-admin
```

To ensure the Gitolite configuration matches on-disk mirrors:

```bash
python -m git_mirror.cli gitolite-sync --base-dir /srv/git \
  --admin-url git@yourhost:gitolite-admin \
  --admin-dir /home/git/gitolite-admin
```
