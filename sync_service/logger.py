"""
Colorful logging configuration for the sync service.

Provides colored console output with different colors for different log levels.
"""

import logging
import sys
from typing import Optional


# ANSI color codes
class Colors:
    """ANSI color codes for terminal output."""

    RESET = "\033[0m"
    BOLD = "\033[1m"

    # Colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Bright colors
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"

    # Background colors
    BG_BLACK = "\033[40m"
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"
    BG_MAGENTA = "\033[45m"
    BG_CYAN = "\033[46m"
    BG_WHITE = "\033[47m"


class ColoredFormatter(logging.Formatter):
    """
    Custom log formatter with colors.

    Examples:
        [INFO] 2024-01-01 12:00:00 - module_name - Message
        [ERROR] 2024-01-01 12:00:00 - module_name - Error message
    """

    # Log level colors
    LEVEL_COLORS = {
        logging.DEBUG: Colors.BRIGHT_BLUE,
        logging.INFO: Colors.BRIGHT_GREEN,
        logging.WARNING: Colors.BRIGHT_YELLOW,
        logging.ERROR: Colors.BRIGHT_RED,
        logging.CRITICAL: Colors.BG_RED + Colors.BRIGHT_WHITE,
    }

    # Log level names
    LEVEL_NAMES = {
        logging.DEBUG: "DEBUG",
        logging.INFO: "INFO",
        logging.WARNING: "WARN",
        logging.ERROR: "ERROR",
        logging.CRITICAL: "CRITICAL",
    }

    def __init__(
        self,
        fmt: Optional[str] = None,
        datefmt: Optional[str] = None,
        use_colors: bool = True,
    ):
        """
        Initialize the colored formatter.

        Args:
            fmt: Log message format
            datefmt: Date format
            use_colors: Whether to use colors (disable for file logging)
        """
        super().__init__(fmt=fmt, datefmt=datefmt)
        self.use_colors = use_colors

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record with colors."""
        if self.use_colors:
            # Get color for this log level
            level_color = self.LEVEL_COLORS.get(record.levelno, "")
            level_name = self.LEVEL_NAMES.get(record.levelno, record.levelname)
            reset = Colors.RESET

            # Add color to level name
            record.levelname = f"{level_color}[{level_name}]{reset}"

            # Add color to the module name
            record.name = f"{Colors.CYAN}{record.name}{reset}"

            # Add bold to message
            record.msg = f"{Colors.BOLD}{record.msg}{reset}"

        return super().format(record)


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    format_string: Optional[str] = None,
) -> None:
    """
    Setup logging with colored console output.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional file path to also log to file (without colors)
        format_string: Custom format string
    """
    # Default format
    if format_string is None:
        format_string = "%(levelname)s %(asctime)s - %(name)s - %(message)s"

    # Get log level
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Create root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers
    root_logger.handlers.clear()

    # Console handler with colors
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_formatter = ColoredFormatter(
        fmt=format_string,
        datefmt="%Y-%m-%d %H:%M:%S",
        use_colors=True,
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # Optional: File handler without colors
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(log_level)
        file_formatter = ColoredFormatter(
            fmt=format_string,
            datefmt="%Y-%m-%d %H:%M:%S",
            use_colors=False,  # No colors in file
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the specified name.

    Args:
        name: Logger name (usually __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


# Quick setup function
def init_logger(level: str = "INFO") -> None:
    """
    Quick initialize logger with colored output.

    Args:
        level: Logging level
    """
    setup_logging(level=level)
