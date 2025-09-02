from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Tuple

SERVICE_TEMPLATE = """[Unit]
Description=Mirror and sync Gitolite ACLs for {base}

[Service]
Type=oneshot
WorkingDirectory={base}
ExecStart={python} -m git_mirror.cli update-all --base-dir {base}
ExecStart={python} -m git_mirror.cli gitolite-sync --base-dir {base}

[Install]
WantedBy=default.target
"""

TIMER_TEMPLATE = """[Unit]
Description=Run git-mirror for {base} periodically

[Timer]
OnBootSec=5min
OnUnitActiveSec=15min
Unit={unit}

[Install]
WantedBy=timers.target
"""


def _unit_name(base: Path) -> str:
    slug = base.resolve().as_posix().replace('/', '-').lstrip('-')
    return f"git-mirror-{slug}.service"


def register_user_service(base: Path) -> Tuple[Path, Path]:
    """Create and enable user-level systemd service and timer for *base*.

    Returns (service_path, timer_path).
    """
    unit = _unit_name(base)
    timer = unit.replace('.service', '.timer')
    user_dir = Path.home() / '.config' / 'systemd' / 'user'
    user_dir.mkdir(parents=True, exist_ok=True)
    service_path = user_dir / unit
    timer_path = user_dir / timer
    python = sys.executable
    service_path.write_text(
        SERVICE_TEMPLATE.format(base=base, python=python), encoding='utf-8'
    )
    timer_path.write_text(
        TIMER_TEMPLATE.format(base=base, unit=unit), encoding='utf-8'
    )
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', '--user', 'enable', '--now', timer], check=True)
    return service_path, timer_path
