"""
全局日志配置模块

提供统一的日志配置管理，使用Python标准logging库的配置功能。
支持日志轮转、彩色输出等特性。

使用方法：
    >>> from ..services.logging_config import setup_logging
    >>> setup_logging()
"""

import logging
import logging.config
import os
import sys
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock


class ColorFormatter(logging.Formatter):
    """
    彩色日志格式化器类

    支持彩色终端输出的日志格式化器，不同级别使用不同颜色。
    """

    # ANSI 颜色代码
    COLORS = {
        "DEBUG": "\033[36m",  # 青色
        "INFO": "\033[32m",  # 绿色
        "WARNING": "\033[33m",  # 黄色
        "ERROR": "\033[31m",  # 红色
        "CRITICAL": "\033[1;31m",  # 红色加粗
    }
    RESET = "\033[0m"

    def __init__(self, fmt: str, datefmt: str):
        super().__init__()
        self.fmt = fmt
        self.datefmt = datefmt

    def format(self, record: logging.LogRecord) -> str:
        """
        格式化日志记录，添加颜色

        Args:
            record: 日志记录对象

        Returns:
            str: 格式化后的彩色日志字符串
        """
        # 获取模块名称
        module = record.name
        if hasattr(record, "log_module") and not isinstance(record.log_module, Mock):
            module = record.log_module

        # 格式化时间
        log_time = datetime.fromtimestamp(record.created).strftime(self.datefmt)

        # 级别名称
        level_name = record.levelname

        # 获取颜色代码
        color = self.COLORS.get(level_name, "")
        reset = self.RESET

        # 格式化输出
        formatted = self.fmt.format(
            time=log_time, module=module, level=level_name, message=record.getMessage()
        )

        # 添加颜色
        return f"{color}{formatted}{reset}"


class SimpleFormatter(logging.Formatter):
    """
    简单日志格式化器类

    内部使用的日志格式化器，支持对齐格式和自定义模板。
    """

    def __init__(self, fmt: str, datefmt: str):
        super().__init__()
        self.fmt = fmt
        self.datefmt = datefmt

    def format(self, record: logging.LogRecord) -> str:
        """
        格式化日志记录

        Args:
            record: 日志记录对象

        Returns:
            str: 格式化后的日志字符串
        """
        # 获取模块名称
        module = record.name
        if hasattr(record, "log_module") and not isinstance(record.log_module, Mock):
            module = record.log_module

        # 格式化时间
        log_time = datetime.fromtimestamp(record.created).strftime(self.datefmt)

        # 级别名称
        level_name = record.levelname

        # 格式化输出
        return self.fmt.format(
            time=log_time, module=module, level=level_name, message=record.getMessage()
        )


def setup_logging(
    level: str = "INFO",
    log_dir: str = "logs",
    enable_file_logging: bool = True,
    rotation_size: str = "10MB",
    rotation_backup_count: int = 5,
    use_colors: bool = True,
    name: str = "autoseek",
):
    """
    设置全局日志配置

    Args:
        level: 日志级别，如 "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
        log_dir: 日志文件目录
        enable_file_logging: 是否启用文件日志记录（云原生环境建议设为 False）
        rotation_size: 文件大小轮转阈值，如 "10MB", "100KB"
        rotation_backup_count: 保留的备份文件数量
        use_colors: 是否使用彩色输出
        name: 日志记录器名称

    Returns:
        logging.Logger: 配置好的日志记录器

    云原生环境使用说明：
    - enable_file_logging=False: 只输出到 stdout/stderr，由 K8s 采集日志
    - enable_file_logging=True: 保留文件日志（用于本地调试）
    - 可通过环境变量 LOG_TO_FILE 控制文件日志开关
    """
    # 检查环境变量，K8s 环境默认不写文件
    if os.getenv("KUBERNETES_SERVICE_HOST") or os.getenv("LOG_TO_FILE", "false").lower() != "true":
        enable_file_logging = False

    # 确保日志目录存在（仅在需要文件日志时）
    log_path = Path(log_dir)
    if enable_file_logging:
        log_path.mkdir(parents=True, exist_ok=True)

    # 解析文件大小
    def parse_size(size_str: str) -> int:
        size_str = size_str.upper().strip()
        units = {
            "B": 1,
            "KB": 1024,
            "MB": 1024 * 1024,
            "GB": 1024 * 1024 * 1024,
        }
        for unit in sorted(units.keys(), key=len, reverse=True):
            if size_str.endswith(unit):
                number_str = size_str[: -len(unit)]
                try:
                    number = float(number_str)
                    return int(number * units[unit])
                except ValueError:
                    raise ValueError(f"无效的文件大小格式: {size_str}")
        try:
            return int(size_str)
        except ValueError:
            raise ValueError(f"无效的文件大小格式: {size_str}")

    # 日志格式
    log_format = "{time} | {module:20} | {level:8} | {message}"
    date_format = "%Y-%m-%d %H:%M:%S"

    # 构建配置字典
    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "()": "sync_service.logging_config.SimpleFormatter",
                "fmt": log_format,
                "datefmt": date_format,
            },
            "colored": {
                "()": "sync_service.logging_config.ColorFormatter",
                "fmt": log_format,
                "datefmt": date_format,
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "colored" if use_colors else "standard",
                "level": level,
            },
        },
        "loggers": {
            "": {  # root logger
                "handlers": ["console"],
                "level": level,
                "propagate": True,
            },
        },
    }

    # 添加文件处理器
    if enable_file_logging:
        max_bytes = parse_size(rotation_size)
        config["handlers"]["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": log_path / "app.log",
            "maxBytes": max_bytes,
            "backupCount": rotation_backup_count,
            "formatter": "standard",
            "level": "DEBUG",  # 文件记录所有级别
            "encoding": "utf-8",
        }
        config["loggers"][""]["handlers"].append("file")

    # 应用配置
    logging.config.dictConfig(config)

    # 配置第三方库日志级别
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

    # 获取日志记录器
    logger = logging.getLogger(name)

    # 输出配置信息
    is_k8s = bool(os.getenv("KUBERNETES_SERVICE_HOST"))
    logger.info(f"日志系统已初始化 - 级别: {level}, 环境: {'Kubernetes' if is_k8s else '本地'}")
    if enable_file_logging:
        logger.info(
            f"文件日志已启用 - 轮转大小: {rotation_size}, 备份数: {rotation_backup_count}"
        )
    else:
        logger.info("文件日志已禁用 - 仅输出到 stdout/stderr")
    if use_colors:
        logger.info("彩色输出已启用")

    return logger


def get_logger(name: str):
    """
    获取日志记录器（快捷方式）

    Args:
        name: 日志记录器名称

    Returns:
        logging.Logger: 标准logging记录器
    """
    return logging.getLogger(name)
