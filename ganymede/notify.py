"""Tell the human something. Prints, and optionally pipes the message to a shell command."""

from __future__ import annotations

import logging
import subprocess

log = logging.getLogger("ganymede")


def notify(message: str, cmd: str | None = None) -> None:
    log.warning("NOTIFY: %s", message)
    if cmd:
        try:
            subprocess.run(cmd, shell=True, input=message.encode(), timeout=60, check=False)
        except Exception as e:  # noqa: BLE001
            log.error("notify command failed: %s", e)
