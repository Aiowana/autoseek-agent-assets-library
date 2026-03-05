"""
Agent Asset Library Sync Service

A service for synchronizing agent assets (tools, prompts, skills)
between GitHub repository and Redis/Tendis storage.
"""

__version__ = "2.0.0"

from sync_service.config import Config, WebhookConfig
from sync_service.logger import Logger, RedisStreamHandler
from sync_service.logging_config import setup_logging, get_logger
from sync_service.models import Asset, ManifestData
from sync_service.redis_client import RedisClient
from sync_service.schema import ManifestValidator
from sync_service.github_manager import GitHubManager
from sync_service.sync_service import AssetSyncService
from sync_service.lock import DistributedLock, LockTimeoutError, create_lock
from sync_service.retry_queue import SyncRetryQueue, create_retry_queue
from sync_service.tenant import (
    TenantConfig,
    TenantRegistry,
    TenantManager,
    get_tenant_manager,
    init_tenant_manager,
)

__all__ = [
    "Config",
    "WebhookConfig",
    "Logger",
    "RedisStreamHandler",
    "setup_logging",
    "get_logger",
    "Asset",
    "ManifestData",
    "RedisClient",
    "ManifestValidator",
    "GitHubManager",
    "AssetSyncService",
    "DistributedLock",
    "LockTimeoutError",
    "create_lock",
    "SyncRetryQueue",
    "create_retry_queue",
    # Multi-tenant
    "TenantConfig",
    "TenantRegistry",
    "TenantManager",
    "get_tenant_manager",
    "init_tenant_manager",
]
