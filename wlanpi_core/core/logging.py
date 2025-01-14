import json
import logging
import pathlib
import traceback
import sys
import os
from typing import Dict, Optional

LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

class ContextualLogRecord(logging.LogRecord):
    """
    Custom LogRecord that captures additional context information
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        if not self.exc_info and sys.exc_info()[0] is not None:
            self.exc_info = sys.exc_info()
            
        if self.levelno >= logging.ERROR and self.exc_info:
            try:
                exc_type, exc_value, exc_traceback = self.exc_info
                tb = traceback.extract_tb(exc_traceback)
                if tb:
                    last_frame = tb[-1]
                    self.source_file = os.path.basename(last_frame.filename)
                    self.line_number = last_frame.lineno
                    self.source_function = last_frame.name
                else:
                    self.source_file = 'Unknown'
                    self.line_number = 0
                    self.source_function = 'Unknown'
            except Exception:
                self.source_file = 'Unknown'
                self.line_number = 0
                self.source_function = 'Unknown'
        else:
            try:
                stack = traceback.extract_stack()
                for frame in reversed(stack[:-2]):  # Exclude the last two frames
                    filename = os.path.basename(frame.filename)
                    lineno = frame.lineno
                    function = frame.name
                    if all(module not in filename for module in ['logging', __file__, 'contextlib']):
                        self.source_file = os.path.basename(filename)
                        self.line_number = lineno
                        self.source_function = function
                        break
                else:
                    self.source_file = 'Unknown'
                    self.line_number = 0
                    self.source_function = 'Unknown'
            except Exception:
                self.source_file = 'Unknown'
                self.line_number = 0
                self.source_function = 'Unknown'
                
class ContextFilter(logging.Filter):
    """
    A logging filter that ensures contextual information is added to log records
    """
    def filter(self, record):
        if not hasattr(record, 'source_file'):
            record.source_file = 'Unknown'
        if not hasattr(record, 'line_number'):
            record.line_number = 0
        if not hasattr(record, 'source_function'):
            record.source_function = 'Unknown'
        return True
    
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
                "source_function": "%(source_function)s",
                "line": "%(line_number)d",
                "source_file": "%(source_file)s",
            }
        )

    def format(self, record: logging.LogRecord) -> str:
        if record.args:
            record.message = record.msg % record.args
        else:
            record.message = str(record.msg)

        message = {}
        for key, value in self.fmt_keys.items():
            if key == "timestamp":
                value = self.formatTime(record, self.datefmt)
            elif key == "message":
                value = record.message
            else:
                try:
                    value = value % record.__dict__
                except (KeyError, ValueError):
                    value = "Unknown"
            message[key] = value

        if record.exc_info:
            message["exc_info"] = self.formatException(record.exc_info)

        if hasattr(record, "extra_fields"):
            message.update(record.extra_fields)

        return json.dumps(message)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with the specified name
    """
    return logging.getLogger(f"{name}")


def configure_logging(debug_mode: bool = False):
    """
    Configure logging with console and file handlers

    Args:
        debug_mode: Whether to force DEBUG level logging
    """
    logging.setLogRecordFactory(ContextualLogRecord)
    
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    debug_log_dir = pathlib.Path("/var/log/wlanpi_core/debug")
    debug_log_dir.mkdir(parents=True, exist_ok=True)

    context_filter = ContextFilter()
    
    console_stream_handler = logging.StreamHandler()
    app_file_handler = logging.FileHandler("/var/log/wlanpi_core/app.log")
    debug_file_handler = logging.FileHandler("/var/log/wlanpi_core/debug/debug.log")

    json_formatter = JsonFormatter()
    standard_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    console_stream_handler.addFilter(context_filter)
    app_file_handler.addFilter(context_filter)
    debug_file_handler.addFilter(context_filter)

    # console - info by default, debug if --debug
    console_stream_handler.setFormatter(standard_formatter)
    console_stream_handler.setLevel(logging.DEBUG if debug_mode else logging.INFO)

    # /var/log/wlanpi_core/app.log - gets info or higher
    app_file_handler.setFormatter(json_formatter)
    app_file_handler.setLevel(logging.INFO)

    # /var/log/wlanpi_core/debug.log (tmpfs) - gets everything
    debug_file_handler.setFormatter(json_formatter)
    debug_file_handler.setLevel(logging.DEBUG)

    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(console_stream_handler)
    root_logger.addHandler(app_file_handler)
    root_logger.addHandler(debug_file_handler)


def test_logging_levels() -> Dict[str, str]:
    """Test function to verify logging levels are working"""
    logger = get_logger("test")

    test_messages = {
        "debug": "This is a debug message",
        "info": "This is an info message",
        "warning": "This is a warning message",
        "error": "This is an error message",
        "critical": "This is a critical message",
    }

    logger.debug(test_messages["debug"])
    logger.info(test_messages["info"])
    logger.warning(test_messages["warning"])
    logger.error(test_messages["error"])
    logger.critical(test_messages["critical"])

    return test_messages
