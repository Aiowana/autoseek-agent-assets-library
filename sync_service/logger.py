"""
日志记录器模块 - 简化包装器 + Redis Stream 支持

基于Python标准logging模块的简化包装器，解决多实例问题。
使用标准logging库的单例机制，提供简洁的接口。

特性：
- 基于Python标准logging模块，完全兼容生态系统
- 真正的单例机制，避免重复处理器问题
- 简洁的接口设计
- 线程/进程安全
- RedisStreamHandler：实时日志推送 + 历史回溯

示例用法：
    >>> from ..services.Logger import Logger
    >>>
    >>> # 创建日志记录器
    >>> logger = Logger("myapp")
    >>> logger.info("应用程序启动")
    >>>
    >>> # 带模块信息的日志
    >>> logger.info("处理用户请求", module="api")
"""

import json
import logging
from typing import Optional


class RedisStreamHandler(logging.Handler):
    """
    将日志流式传输到 Redis 的 Handler

    功能：
    1. 实时推送：Redis Pub/Sub 用于前端实时订阅
    2. 历史回溯：Redis List 存储最近 N 条日志
    3. 动态路由：根据 log_module 字段（entity_id）分发到不同频道

    Attributes:
        redis: Redis 客户端实例
        project_id: 项目 ID，用于 Hash Tag 构造
        max_history: 历史日志最大条数
    """

    def __init__(
        self,
        redis_client,
        project_id: str,
        max_history: int = 100,
        level: int = logging.INFO,
    ):
        super().__init__(level=level)
        self.redis = redis_client
        self.project_id = project_id
        self.max_history = max_history

    def emit(self, record: logging.LogRecord) -> None:
        """
        处理日志记录

        Args:
            record: logging.LogRecord，包含 log_module 字段作为 entity_id
        """
        try:
            # 1. 获取 entity_id（从 log_module 字段）
            entity_id = getattr(record, "log_module", record.name)

            # 2. 构建日志 Payload
            payload = {
                "ts": record.created,
                "level": record.levelname,
                "entity_id": entity_id,
                "logger_name": record.name,
                "msg": self.format(record),
                "module": record.module,
                "line": record.lineno,
            }

            payload_str = json.dumps(payload, default=str, ensure_ascii=False)

            # 3. 构建 Redis Keys（使用 Hash Tag）
            pub_channel = f"logs:stream:{{p:{self.project_id}}}:{entity_id}"
            history_key = f"logs:history:{{p:{self.project_id}}}:{entity_id}"

            # 4. 使用 Pipeline 执行原子操作
            pipe = self.redis.pipeline(transaction=False)
            pipe.publish(pub_channel, payload_str)
            pipe.lpush(history_key, payload_str)
            pipe.ltrim(history_key, 0, self.max_history - 1)
            pipe.expire(history_key, 60 * 60 * 24)  # 24小时过期
            pipe.execute()

        except Exception:
            # 不阻塞日志流程，只记录错误
            self.handleError(record)

    def close(self) -> None:
        """关闭 Handler"""
        try:
            super().close()
        except Exception:
            pass


class Logger:
    """
    日志记录器类 - 简化包装器

    提供简洁的日志接口，使用标准logging库的单例机制。

    Attributes:
        name (str): 日志记录器名称
        _logger (logging.Logger): 底层标准日志记录器实例

    Methods:
        __init__: 初始化日志记录器
        debug: 记录DEBUG级别日志
        info: 记录INFO级别日志
        warning: 记录WARNING级别日志
        error: 记录ERROR级别日志
        critical: 记录CRITICAL级别日志
    """

    def __init__(self, name: str):
        """
        初始化日志记录器

        Args:
            name: 日志记录器名称，使用标准logging的单例机制
        """
        self.name = name
        self._logger = logging.getLogger(name)

        # 如果没有全局配置，自动设置基本配置
        if not logging.getLogger().handlers:
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

    def _log_with_extra(
        self,
        level: int,
        message: str,
        module: Optional[str] = None,
    ) -> None:
        """内部方法：带 extra 字段记录日志"""
        extra = {"log_module": module} if module else {}
        self._logger.log(level, message, extra=extra)

    def debug(self, message: str, module: Optional[str] = None) -> None:
        """记录DEBUG级别日志"""
        self._log_with_extra(logging.DEBUG, message, module)

    def info(self, message: str, module: Optional[str] = None) -> None:
        """记录INFO级别日志"""
        self._log_with_extra(logging.INFO, message, module)

    def warning(self, message: str, module: Optional[str] = None) -> None:
        """记录WARNING级别日志"""
        self._log_with_extra(logging.WARNING, message, module)

    def error(self, message: str, module: Optional[str] = None) -> None:
        """记录ERROR级别日志"""
        self._log_with_extra(logging.ERROR, message, module)

    def critical(self, message: str, module: Optional[str] = None) -> None:
        """记录CRITICAL级别日志"""
        self._log_with_extra(logging.CRITICAL, message, module)
