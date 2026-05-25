from __future__ import annotations

import logging
import os
import sys


class _ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "\033[2;37m",
        logging.INFO: "\033[0;36m",
        logging.WARNING: "\033[0;33m",
        logging.ERROR: "\033[0;31m",
        logging.CRITICAL: "\033[1;31m",
    }
    RESET = "\033[0m"

    def __init__(self, color: bool):
        super().__init__("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S")
        self.color = color

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        if self.color:
            return f"{self.COLORS.get(record.levelno, '')}{text}{self.RESET}"
        return text


def configure() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_ColorFormatter(color=sys.stdout.isatty()))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(level)
