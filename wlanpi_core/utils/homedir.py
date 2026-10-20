"""Ownership self-heal for the wlanpi user's XDG data-home tree.

A root-run ``mkdir(parents=True)`` leaves a missing ``~wlanpi/.local`` or
``.local/share`` root-owned. They are shared with other wlanpi apps and must
stay wlanpi:wlanpi; only ``.local/share/wlanpi-core`` is root's.
"""

import grp
import os
import pwd
from pathlib import Path

from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)


def ensure_wlanpi_home_data_dirs(home_dir: Path) -> None:
    """Ensure ``home_dir/.local`` and ``home_dir/.local/share`` are wlanpi-owned.

    Creates either directory if missing, and reclaims ownership if a prior
    run left it root-owned. Does nothing if the wlanpi user/group don't
    exist (e.g. under test).
    """
    try:
        pw = pwd.getpwnam("wlanpi")
        gid = grp.getgrnam("wlanpi").gr_gid
    except KeyError:
        return

    for rel in (Path(".local"), Path(".local") / "share"):
        target = home_dir / rel
        try:
            if not target.exists():
                target.mkdir(mode=0o755, exist_ok=True)
                os.chown(str(target), pw.pw_uid, gid)
                continue

            st = target.stat()
            if st.st_uid != pw.pw_uid or st.st_gid != gid:
                log.info(f"Reclaiming wlanpi ownership of {target}")
                os.chown(str(target), pw.pw_uid, gid)
        except OSError as e:
            log.warning(f"Could not ensure wlanpi ownership of {target}: {e}")
