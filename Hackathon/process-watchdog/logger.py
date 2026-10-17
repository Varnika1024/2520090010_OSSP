"""Logging setup: timestamped events to the console and (optionally) a rotating file."""
import logging
import os
from logging.handlers import RotatingFileHandler

FORMAT = "%(asctime)s [%(levelname)s] %(message)s"


def setup_logger(log_file=None, level="INFO"):
    log = logging.getLogger("watchdog")
    log.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    log.handlers.clear()
    fmt = logging.Formatter(FORMAT)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    log.addHandler(console)

    if log_file:
        os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
        fh = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3)
        fh.setFormatter(fmt)
        log.addHandler(fh)
    log.propagate = False
    return log
