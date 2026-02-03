"""
Agent Asset Library Sync Service

A service for synchronizing agent assets (tools, prompts, skills)
between GitHub repository and Redis/Tendis storage.
"""

__version__ = "1.1.0"

from sync_service.config import Config
from sync_service.logger import Logger, RedisStreamHandler
from sync_service.logging_config import setup_logging, get_logger
from sync_service.models import Asset, ManifestData
from sync_service.redis_client import RedisClient
from sync_service.schema import ManifestValidator
from sync_service.github_manager import GitHubManager
from sync_service.sync_service import AssetSyncService

__all__ = [
    "Config",
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
]
