from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from . import config

log = logging.getLogger("subforge")


def setup(verbose: bool = False) -> logging.Logger:
    if log.handlers:
        return log
    log.setLevel(logging.DEBUG)
    config.LOGS.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(config.LOGS / "subforge.log", maxBytes=1_000_000, backupCount=3,
                             encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    fh.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(message)s"))
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    log.addHandler(fh)
    log.addHandler(ch)
    return log
