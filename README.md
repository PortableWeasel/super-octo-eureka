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

## System integration

Example systemd units are provided in `examples/systemd`.
Install and enable them with:

```bash
sudo cp examples/systemd/git-mirror.service /etc/systemd/system/
sudo cp examples/systemd/git-mirror.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now git-mirror.timer
```

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
