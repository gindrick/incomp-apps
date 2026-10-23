"""Logování na standardní výstup a volitelně do rotovaného souboru."""
from __future__ import annotations

import logging
import logging.handlers
import os

from .config import Settings

_CONFIGURED = False


def setup_logging(settings: Settings) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)
    if settings.log_dir:
        os.makedirs(settings.log_dir, exist_ok=True)
        fh = logging.handlers.TimedRotatingFileHandler(
            os.path.join(settings.log_dir, "semafor.log"), when="midnight", backupCount=30, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    _CONFIGURED = True
