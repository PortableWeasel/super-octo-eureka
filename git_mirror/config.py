from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path
from typing import Optional

CONFIG_FILENAME = ".git-mirror.conf"
SECTION = "git-mirror"

def config_path(base_dir: Path) -> Path:
    """Return the path to the config file inside *base_dir*."""
    return base_dir / CONFIG_FILENAME

def load_config(base_dir: Path) -> ConfigParser:
    """Load configuration from *base_dir*.

    If the file does not exist an empty ConfigParser is returned.
    """
    cfg = ConfigParser()
    path = config_path(base_dir)
    if path.exists():
        cfg.read(path)
    return cfg

def save_config(base_dir: Path, cfg: ConfigParser) -> None:
    """Persist *cfg* in *base_dir*."""
    path = config_path(base_dir)
    with path.open("w") as fh:
        cfg.write(fh)

def get_value(base_dir: Path, key: str, default: Optional[str] = None) -> Optional[str]:
    """Return the value for *key* from config under *base_dir*."""
    cfg = load_config(base_dir)
    if cfg.has_option(SECTION, key):
        return cfg.get(SECTION, key)
    return default

def set_value(base_dir: Path, key: str, value: str) -> None:
    """Set *key* to *value* in config under *base_dir*."""
    cfg = load_config(base_dir)
    if not cfg.has_section(SECTION):
        cfg.add_section(SECTION)
    cfg.set(SECTION, key, value)
    save_config(base_dir, cfg)

def find_base_dir(start: Optional[Path] = None) -> Optional[Path]:
    """Search upwards from *start* (or CWD) for the config file.

    Returns the directory containing the config, or ``None`` if not found.
    """
    current = start or Path.cwd()
    for path in [current, *current.parents]:
        if (path / CONFIG_FILENAME).exists():
            return path
    return None
