"""
分布式锁实现

使用 Redis 实现分布式锁，防止多个同步进程同时运行。
"""

import hashlib
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)


class DistributedLock:
    """
    分布式锁

    使用 Redis SET NX EX 命令实现分布式锁，支持自动过期和手动释放。
    """

    def __init__(self, redis_client, key: str, timeout: int = 60):
        """
        初始化分布式锁

        Args:
            redis_client: Redis 客户端实例
            key: 锁的键名（会自动添加前缀）
            timeout: 锁的超时时间（秒），防止死锁
        """
        self.redis = redis_client
        self.key = f"asset:sync:lock:{key}"
        self.timeout = timeout
        self.lock_value: Optional[str] = None
        self.acquired = False

    def acquire(self) -> bool:
        """
        获取锁

        使用 SET NX EX 命令原子性地获取锁。
        锁值使用 "进程ID:时间戳" 格式，用于释放时验证。

        Returns:
            bool: 是否成功获取锁
        """
        self.lock_value = f"{os.getpid()}:{time.time()}"

        # SET key value NX EX seconds
        # NX: 只在 key 不存在时设置
        # EX: 设置过期时间
        result = self.redis.set(self.key, self.lock_value, nx=True, ex=self.timeout)

        if result:
            self.acquired = True
            logger.info(f"Lock acquired: {self.key}")
        else:
            current_value = self.redis.get(self.key)
            logger.warning(
                f"Lock already held: {self.key} (current: {current_value[:20]}...)"
            )

        return bool(result)

    def release(self) -> bool:
        """
        释放锁

        使用 Lua 脚本原子性地验证并释放锁，只释放自己持有的锁。

        Returns:
            bool: 是否成功释放锁
        """
        if not self.acquired:
            logger.warning(f"Lock not acquired, cannot release: {self.key}")
            return False

        # Lua 脚本：只删除 value 匹配的 key
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """

        try:
            result = self.redis.eval(lua_script, 1, self.key, self.lock_value)
            if result:
                self.acquired = False
                logger.info(f"Lock released: {self.key}")
                return True
            else:
                logger.warning(
                    f"Lock value mismatch, possibly expired or stolen: {self.key}"
                )
                self.acquired = False
                return False
        except Exception as e:
            logger.error(f"Error releasing lock: {e}", exc_info=True)
            return False

    def extend(self, additional_time: int = None) -> bool:
        """
        延长锁的过期时间

        Args:
            additional_time: 延长的秒数，默认为初始超时时间

        Returns:
            bool: 是否成功延长
        """
        if not self.acquired:
            return False

        expire_time = additional_time or self.timeout

        # Lua 脚本：只延长 value 匹配的 key
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("expire", KEYS[1], ARGV[2])
        else
            return 0
        end
        """

        try:
            result = self.redis.eval(lua_script, 1, self.key, self.lock_value, expire_time)
            if result:
                logger.info(f"Lock extended: {self.key} (+{expire_time}s)")
            return bool(result)
        except Exception as e:
            logger.error(f"Error extending lock: {e}", exc_info=True)
            return False

    def is_locked(self) -> bool:
        """
        检查锁是否被持有（不检查是否是自己持有）

        Returns:
            bool: 锁是否存在
        """
        return self.redis.exists(self.key) == 1

    def get_ttl(self) -> int:
        """
        获取锁的剩余 TTL（秒）

        Returns:
            int: 剩余秒数，-2 表示锁不存在，-1 表示锁没有过期时间
        """
        return self.redis.ttl(self.key)

    def __enter__(self):
        """支持 with 语句"""
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """支持 with 语句"""
        self.release()


class LockTimeoutError(Exception):
    """获取锁超时异常"""
    pass


def acquire_lock_with_retry(
    redis_client,
    key: str,
    timeout: int = 60,
    wait_timeout: int = 0,
    wait_interval: float = 0.1,
) -> Optional[DistributedLock]:
    """
    带重试的锁获取

    Args:
        redis_client: Redis 客户端
        key: 锁的键名
        timeout: 锁的超时时间
        wait_timeout: 等待获取锁的最长时间（0 表示不等待）
        wait_interval: 重试间隔（秒）

    Returns:
        DistributedLock 实例，如果获取失败则返回 None
    """
    lock = DistributedLock(redis_client, key, timeout)

    if lock.acquire():
        return lock

    if wait_timeout <= 0:
        return None

    start_time = time.time()
    while time.time() - start_time < wait_timeout:
        time.sleep(wait_interval)
        if lock.acquire():
            return lock

    logger.error(f"Failed to acquire lock after {wait_timeout}s: {key}")
    return None


def create_lock(redis_client, key: str, timeout: int = 60) -> DistributedLock:
    """创建分布式锁"""
    return DistributedLock(redis_client, key, timeout)
