import json
import logging
import os
import pathlib
from typing import Dict, Optional

LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


class JsonFormatter(logging.Formatter):
    """JSON log formatter"""

    def __init__(
        self,
        *,
        fmt_keys: Optional[Dict[str, str]] = None,
    ):
        super().__init__()
        self.fmt_keys = (
            fmt_keys
            if fmt_keys is not None
            else {
                "timestamp": "%(asctime)s",
                "level": "%(levelname)s",
                "message": "%(message)s",
                "logger": "%(name)s",
                "module": "%(module)s",
                "function": "%(funcName)s",
                "line": "%(lineno)d",
            }
        )

    def format(self, record: logging.LogRecord) -> str:
        message = {}
        for key, value in self.fmt_keys.items():
            if key == "timestamp":
                value = self.formatTime(record, self.datefmt)
            else:
                value = value % record.__dict__
            message[key] = value

        if record.exc_info:
            message["exc_info"] = self.formatException(record.exc_info)

        if hasattr(record, "extra_fields"):
            message.update(record.extra_fields)

        return json.dumps(message)


def get_log_level() -> int:
    """
    Get logging level from environment variable with a default

    Uses WLANPI_LOG_LEVEL environment variable
    Defaults to INFO if not set or invalid
    """
    level_name = os.environ.get("WLANPI_LOG_LEVEL", "INFO").upper()
    return LOG_LEVELS.get(level_name, logging.INFO)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with the specified name

    Prefixes the logger name with 'wlanpi_core.' for consistent naming
    """
    return logging.getLogger(f"{name}")


def set_log_level(level: str) -> None:
    """
    Set logging level for all application loggers

    Args:
        level: Log level to set (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    level = level.upper()
    if level not in LOG_LEVELS:
        raise ValueError(f"Invalid log level: {level}")

    numeric_level = LOG_LEVELS[level]

    logging.getLogger().setLevel(numeric_level)

    for logger_name in logging.root.manager.loggerDict:
        if logger_name.startswith("wlanpi_core"):
            logger = logging.getLogger(logger_name)
            logger.setLevel(numeric_level)

    get_logger("logging").info(f"Log level changed to {level}")


def configure_logging(level: Optional[int] = None, debug_mode: bool = False):
    if debug_mode:
        log_level = logging.DEBUG
    elif level is not None:
        log_level = level
    else:
        log_level = get_log_level()

    debug_log_dir = pathlib.Path("/var/log/wlanpi-core/debug")
    debug_log_dir.mkdir(parents=True, exist_ok=True)

    console_handler = logging.StreamHandler()
    file_handler = logging.FileHandler("/var/log/wlanpi-core/app.log")
    debug_file_handler = logging.FileHandler("/var/log/wlanpi-core/debug/debug.log")

    json_formatter = JsonFormatter()
    standard_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    console_handler.setFormatter(standard_formatter)
    console_handler.setLevel(log_level)
    file_handler.setFormatter(json_formatter)
    debug_file_handler.setFormatter(json_formatter)
    debug_file_handler.setLevel(logging.DEBUG)

    logging.basicConfig(
        level=log_level, handlers=[console_handler, file_handler, debug_file_handler]
    )

    logging.info(f"Logging configured at {logging.getLevelName(log_level)} level")
