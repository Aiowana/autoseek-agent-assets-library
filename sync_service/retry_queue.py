"""
同步重试队列

处理失败的同步操作，支持指数退避重试。
"""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# 最大重试次数
MAX_RETRIES = 3

# 重试队列 Redis key
RETRY_QUEUE_KEY = "asset:sync:retry_queue"


@dataclass
class RetryItem:
    """重试项"""

    sync_type: str  # "incremental_sync" | "full_sync" | "webhook_sync"
    error: str  # 错误信息
    retry_count: int = 0
    created_at: float = field(default_factory=lambda: time.time())
    last_retry_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sync_type": self.sync_type,
            "error": self.error,
            "retry_count": self.retry_count,
            "created_at": self.created_at,
            "last_retry_at": self.last_retry_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RetryItem":
        return cls(
            sync_type=data["sync_type"],
            error=data["error"],
            retry_count=data.get("retry_count", 0),
            created_at=data.get("created_at", time.time()),
            last_retry_at=data.get("last_retry_at"),
            metadata=data.get("metadata", {}),
        )


class SyncRetryQueue:
    """
    同步重试队列

    管理失败的同步操作，支持指数退避重试。
    """

    def __init__(self, redis_client, max_retries: int = MAX_RETRIES):
        """
        初始化重试队列

        Args:
            redis_client: Redis 客户端
            max_retries: 最大重试次数
        """
        self.redis = redis_client
        self.max_retries = max_retries

    def add_failure(
        self,
        sync_type: str,
        error: Exception,
        retry_count: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        添加失败记录到队列

        Args:
            sync_type: 同步类型
            error: 异常对象
            retry_count: 当前重试次数
            metadata: 额外的元数据
        """
        item = RetryItem(
            sync_type=sync_type,
            error=str(error),
            retry_count=retry_count,
            metadata=metadata or {},
        )

        self.redis.lpush(RETRY_QUEUE_KEY, json.dumps(item.to_dict()))
        logger.info(
            f"Added to retry queue: {sync_type} (retry_count={retry_count})"
        )

    def add_failure_with_delay(
        self,
        sync_type: str,
        error: Exception,
        retry_count: int = 0,
        delay_seconds: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        添加失败记录到队列，并设置延迟重试时间

        Args:
            sync_type: 同步类型
            error: 异常对象
            retry_count: 当前重试次数
            delay_seconds: 延迟执行时间（秒）
            metadata: 额外的元数据
        """
        item = RetryItem(
            sync_type=sync_type,
            error=str(error),
            retry_count=retry_count,
            metadata=metadata or {},
        )

        # 如果有延迟，添加到有序集合，按时间排序
        if delay_seconds > 0:
            score = time.time() + delay_seconds
            self.redis.zadd(f"{RETRY_QUEUE_KEY}:delayed", {json.dumps(item.to_dict()): score})
            logger.info(
                f"Added to delayed retry queue: {sync_type} (delay={delay_seconds}s)"
            )
        else:
            self.redis.lpush(RETRY_QUEUE_KEY, json.dumps(item.to_dict()))
            logger.info(f"Added to retry queue: {sync_type}")

    def get_next(self) -> Optional[RetryItem]:
        """
        获取下一个待重试项

        Returns:
            RetryItem 或 None
        """
        # 先检查延迟队列
        now = time.time()
        delayed_items = self.redis.zrangebyscore(
            f"{RETRY_QUEUE_KEY}:delayed", 0, now, start=0, num=1
        )

        if delayed_items:
            item_data = delayed_items[0]
            # 从延迟队列中移除
            self.redis.zrem(f"{RETRY_QUEUE_KEY}:delayed", item_data)
            return RetryItem.from_dict(json.loads(item_data))

        # 从普通队列获取
        item_data = self.redis.rpop(RETRY_QUEUE_KEY)
        if item_data:
            return RetryItem.from_dict(json.loads(item_data))

        return None

    def process_retries(
        self,
        sync_func: Callable[[str], Any],
        max_items: int = 10,
    ) -> Dict[str, Any]:
        """
        处理重试队列

        Args:
            sync_func: 同步函数，接收 sync_type 参数
            max_items: 最多处理的项目数

        Returns:
            处理结果统计
        """
        stats = {
            "processed": 0,
            "success": 0,
            "failed": 0,
            "exhausted": 0,
            "errors": [],
        }

        for _ in range(max_items):
            item = self.get_next()
            if not item:
                break

            stats["processed"] += 1

            # 检查重试次数
            if item.retry_count >= self.max_retries:
                logger.error(
                    f"Retry exhausted for {item.sync_type}: {item.error}"
                )
                stats["exhausted"] += 1
                stats["errors"].append(f"{item.sync_type}: {item.error}")
                continue

            # 计算退避时间
            wait_time = 2 ** item.retry_count  # 指数退避
            if wait_time > 0:
                logger.info(f"Waiting {wait_time}s before retry...")
                time.sleep(wait_time)

            # 执行重试
            try:
                logger.info(
                    f"Retrying {item.sync_type} (attempt {item.retry_count + 1})"
                )
                result = sync_func(item.sync_type)

                # 记录成功
                stats["success"] += 1
                logger.info(f"Retry succeeded: {item.sync_type}")

            except Exception as e:
                # 重新加入队列，增加重试次数
                stats["failed"] += 1
                logger.error(f"Retry failed: {item.sync_type} - {e}")

                self.add_failure(
                    item.sync_type, e, retry_count=item.retry_count + 1
                )

        return stats

    def get_queue_status(self) -> Dict[str, Any]:
        """
        获取队列状态

        Returns:
            队列状态信息
        """
        queue_length = self.redis.llen(RETRY_QUEUE_KEY)
        delayed_length = self.redis.zcard(f"{RETRY_QUEUE_KEY}:delayed")

        # 获取队列中的前几项
        items = []
        for item_data in self.redis.lrange(RETRY_QUEUE_KEY, 0, 9):
            item = RetryItem.from_dict(json.loads(item_data))
            items.append({
                "sync_type": item.sync_type,
                "retry_count": item.retry_count,
                "error": item.error[:100],  # 限制长度
                "created_at": datetime.fromtimestamp(item.created_at).isoformat(),
            })

        return {
            "queue_length": queue_length,
            "delayed_length": delayed_length,
            "total_pending": queue_length + delayed_length,
            "max_retries": self.max_retries,
            "sample_items": items,
        }

    def clear(self) -> int:
        """
        清空重试队列

        Returns:
            删除的项目数
        """
        count = self.redis.llen(RETRY_QUEUE_KEY)
        self.redis.delete(RETRY_QUEUE_KEY)
        self.redis.delete(f"{RETRY_QUEUE_KEY}:delayed")
        return count


def create_retry_queue(redis_client, max_retries: int = MAX_RETRIES) -> SyncRetryQueue:
    """创建重试队列"""
    return SyncRetryQueue(redis_client, max_retries)
