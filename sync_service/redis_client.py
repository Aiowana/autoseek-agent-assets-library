"""
Redis client wrapper for asset storage operations.

Implements the Redis key conventions defined in REDIS_KEY_CONVENTION.md
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import redis
from redis import Redis

from sync_service.config import RedisConfig
from sync_service.models import StoredAsset

logger = logging.getLogger(__name__)


# ============================================================================
# Key Templates
# ============================================================================

class RedisKeys:
    """Redis key templates following the naming convention."""

    # Asset metadata: asset:metadata:{id}
    METADATA = "asset:metadata:{}"

    # Category index: asset:category:{category}
    CATEGORY = "asset:category:{}"

    # Global index: asset:index (lightweight asset summary)
    GLOBAL_INDEX = "asset:index"

    # Sync state: asset:sync:state
    SYNC_STATE = "asset:sync:state"

    # Changed queue: asset:sync:changed
    SYNC_CHANGED = "asset:sync:changed"

    @classmethod
    def metadata_key(cls, asset_id: str) -> str:
        return cls.METADATA.format(asset_id)

    @classmethod
    def category_key(cls, category: str) -> str:
        return cls.CATEGORY.format(category)

    @staticmethod
    def make_hash(asset: StoredAsset) -> Dict[str, str]:
        """Convert StoredAsset to Redis hash fields."""
        return asset.to_dict()

    @staticmethod
    def make_index_entry(asset: StoredAsset) -> str:
        """
        Create a lightweight index entry for global index.

        Contains only essential fields for list display.
        """
        index_data = {
            "id": asset.id,
            "name": asset.name,
            "category": asset.category,
            "version": asset.version,
            "description": asset.description[:100] if asset.description else "",  # Truncate long descriptions
        }
        return json.dumps(index_data, ensure_ascii=False)


# ============================================================================
# Redis Client
# ============================================================================

class RedisClient:
    """
    Redis client wrapper for asset storage operations.

    Implements all Redis operations following the key naming convention.
    """

    def __init__(self, config: RedisConfig):
        """
        Initialize Redis client.

        Args:
            config: Redis configuration
        """
        self.config = config
        self._client: Optional[Redis] = None

    @property
    def client(self) -> Redis:
        """Lazy initialization of Redis client."""
        if self._client is None:
            self._client = redis.Redis(
                host=self.config.host,
                port=self.config.port,
                password=self.config.password,
                db=self.config.db,
                decode_responses=self.config.decode_responses,
            )
            # Test connection
            self._client.ping()
            logger.info(f"Connected to Redis at {self.config.host}:{self.config.port}")
        return self._client

    # ========================================================================
    # Asset Metadata Operations
    # ========================================================================

    def save_asset(self, asset: StoredAsset, pipeline: Optional[redis.client.Pipeline] = None) -> bool:
        """
        Save asset metadata to Redis.

        Args:
            asset: StoredAsset to save
            pipeline: Optional Redis pipeline for atomic operations

        Returns:
            True if successful
        """
        key = RedisKeys.metadata_key(asset.id)
        data = RedisKeys.make_hash(asset)

        client = pipeline or self.client

        try:
            client.hset(key, mapping=data)
            logger.debug(f"Saved asset metadata: {asset.id}")
            return True
        except redis.RedisError as e:
            logger.error(f"Failed to save asset {asset.id}: {e}")
            return False

    def get_asset(self, asset_id: str) -> Optional[StoredAsset]:
        """
        Retrieve asset metadata from Redis.

        Args:
            asset_id: Asset identifier

        Returns:
            StoredAsset if found, None otherwise
        """
        key = RedisKeys.metadata_key(asset_id)

        try:
            data = self.client.hgetall(key)
            if not data:
                return None
            return StoredAsset.from_dict(data)
        except redis.RedisError as e:
            logger.error(f"Failed to get asset {asset_id}: {e}")
            return None

    def delete_asset(self, asset_id: str, pipeline: Optional[redis.client.Pipeline] = None) -> bool:
        """
        Delete asset metadata from Redis.

        Args:
            asset_id: Asset identifier
            pipeline: Optional Redis pipeline for atomic operations

        Returns:
            True if successful
        """
        key = RedisKeys.metadata_key(asset_id)
        client = pipeline or self.client

        try:
            client.delete(key)
            logger.debug(f"Deleted asset metadata: {asset_id}")
            return True
        except redis.RedisError as e:
            logger.error(f"Failed to delete asset {asset_id}: {e}")
            return False

    def get_all_assets(self) -> List[StoredAsset]:
        """
        Get all assets from Redis.

        Returns:
            List of all StoredAsset objects
        """
        pattern = RedisKeys.METADATA.replace("{}", "*")
        assets = []

        try:
            for key in self.client.scan_iter(match=pattern):
                data = self.client.hgetall(key)
                if data:
                    assets.append(StoredAsset.from_dict(data))
        except redis.RedisError as e:
            logger.error(f"Failed to scan assets: {e}")

        return assets

    # ========================================================================
    # Category Index Operations
    # ========================================================================

    def add_to_category(self, asset_id: str, category: str, pipeline: Optional[redis.client.Pipeline] = None) -> bool:
        """
        Add asset ID to category index.

        Args:
            asset_id: Asset identifier
            category: Category name (tool, prompt, skill)
            pipeline: Optional Redis pipeline for atomic operations

        Returns:
            True if successful
        """
        key = RedisKeys.category_key(category)
        client = pipeline or self.client

        try:
            client.sadd(key, asset_id)
            logger.debug(f"Added {asset_id} to category {category}")
            return True
        except redis.RedisError as e:
            logger.error(f"Failed to add {asset_id} to category {category}: {e}")
            return False

    def remove_from_category(self, asset_id: str, category: str, pipeline: Optional[redis.client.Pipeline] = None) -> bool:
        """
        Remove asset ID from category index.

        Args:
            asset_id: Asset identifier
            category: Category name (tool, prompt, skill)
            pipeline: Optional Redis pipeline for atomic operations

        Returns:
            True if successful
        """
        key = RedisKeys.category_key(category)
        client = pipeline or self.client

        try:
            client.srem(key, asset_id)
            logger.debug(f"Removed {asset_id} from category {category}")
            return True
        except redis.RedisError as e:
            logger.error(f"Failed to remove {asset_id} from category {category}: {e}")
            return False

    def get_by_category(self, category: str) -> List[str]:
        """
        Get all asset IDs in a category.

        Args:
            category: Category name (tool, prompt, skill)

        Returns:
            List of asset IDs
        """
        key = RedisKeys.category_key(category)

        try:
            members = self.client.smembers(key)
            return list(members) if members else []
        except redis.RedisError as e:
            logger.error(f"Failed to get category {category}: {e}")
            return []

    # ========================================================================
    # Atomic Asset Operations
    # ========================================================================

    def save_asset_atomic(self, asset: StoredAsset, old_category: Optional[str] = None) -> bool:
        """
        Save asset with atomic category index update.

        Args:
            asset: StoredAsset to save
            old_category: Previous category if changed

        Returns:
            True if successful
        """
        try:
            pipeline = self.client.pipeline()

            # Save metadata
            self.save_asset(asset, pipeline)

            # Update category index
            new_category = asset.category

            if old_category and old_category != new_category:
                # Remove from old category
                self.remove_from_category(asset.id, old_category, pipeline)

            # Add to new category (idempotent)
            self.add_to_category(asset.id, new_category, pipeline)

            # Update global index
            self.update_global_index(asset, pipeline)

            pipeline.execute()
            logger.info(f"Atomically saved asset: {asset.id} (category: {new_category})")
            return True

        except redis.RedisError as e:
            logger.error(f"Failed to atomically save asset {asset.id}: {e}")
            return False

    def delete_asset_atomic(self, asset_id: str) -> bool:
        """
        Delete asset with atomic category index update.

        Args:
            asset_id: Asset identifier

        Returns:
            True if successful
        """
        try:
            # Get asset first to know its category
            asset = self.get_asset(asset_id)
            if not asset:
                logger.warning(f"Asset not found for deletion: {asset_id}")
                return False

            pipeline = self.client.pipeline()

            # Remove from category index
            self.remove_from_category(asset_id, asset.category, pipeline)

            # Delete metadata
            self.delete_asset(asset_id, pipeline)

            # Remove from global index
            self.remove_from_global_index(asset_id, pipeline)

            pipeline.execute()
            logger.info(f"Atomically deleted asset: {asset_id}")
            return True

        except redis.RedisError as e:
            logger.error(f"Failed to atomically delete asset {asset_id}: {e}")
            return False

    # ========================================================================
    # Global Index Operations (Lightweight Asset List)
    # ========================================================================

    def update_global_index(self, asset: StoredAsset, pipeline: Optional[redis.client.Pipeline] = None) -> bool:
        """
        Update global lightweight index for an asset.

        Args:
            asset: StoredAsset to update in index
            pipeline: Optional Redis pipeline for atomic operations

        Returns:
            True if successful
        """
        client = pipeline or self.client
        index_entry = RedisKeys.make_index_entry(asset)

        try:
            client.hset(RedisKeys.GLOBAL_INDEX, asset.id, index_entry)
            logger.debug(f"Updated global index for: {asset.id}")
            return True
        except redis.RedisError as e:
            logger.error(f"Failed to update global index for {asset.id}: {e}")
            return False

    def remove_from_global_index(self, asset_id: str, pipeline: Optional[redis.client.Pipeline] = None) -> bool:
        """
        Remove asset from global index.

        Args:
            asset_id: Asset identifier
            pipeline: Optional Redis pipeline for atomic operations

        Returns:
            True if successful
        """
        client = pipeline or self.client

        try:
            client.hdel(RedisKeys.GLOBAL_INDEX, asset_id)
            logger.debug(f"Removed {asset_id} from global index")
            return True
        except redis.RedisError as e:
            logger.error(f"Failed to remove {asset_id} from global index: {e}")
            return False

    def get_global_index(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all assets from global lightweight index.

        Returns:
            Dictionary mapping asset_id to index data
            {
                "asset_id": {"id": "...", "name": "...", "category": "...", "version": "...", "description": "..."}
            }
        """
        try:
            data = self.client.hgetall(RedisKeys.GLOBAL_INDEX)
            return {k: json.loads(v) for k, v in data.items()}
        except redis.RedisError as e:
            logger.error(f"Failed to get global index: {e}")
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse global index data: {e}")
            return {}

    def get_all_asset_ids(self) -> List[str]:
        """
        Get all asset IDs from global index.

        Returns:
            List of asset IDs
        """
        try:
            return list(self.client.hkeys(RedisKeys.GLOBAL_INDEX))
        except redis.RedisError as e:
            logger.error(f"Failed to get asset IDs from global index: {e}")
            return []

    # ========================================================================
    # Sync State Operations
    # ========================================================================

    def get_sync_state(self) -> Dict[str, Any]:
        """Get current sync state."""
        try:
            data = self.client.hgetall(RedisKeys.SYNC_STATE)
            return data if data else {}
        except redis.RedisError as e:
            logger.error(f"Failed to get sync state: {e}")
            return {}

    def set_sync_state(self, **kwargs) -> bool:
        """
        Update sync state fields.

        Args:
            **kwargs: Field name/value pairs to update

        Returns:
            True if successful
        """
        try:
            self.client.hset(RedisKeys.SYNC_STATE, mapping=kwargs)
            return True
        except redis.RedisError as e:
            logger.error(f"Failed to set sync state: {e}")
            return False

    def get_last_sync_time(self) -> Optional[int]:
        """Get last sync timestamp."""
        state = self.get_sync_state()
        last_time = state.get("last_sync_time")
        return int(last_time) if last_time else None

    def set_last_sync_time(self, timestamp: int) -> bool:
        """Update last sync timestamp."""
        return self.set_sync_state(last_sync_time=str(timestamp))

    def get_last_commit_sha(self) -> Optional[str]:
        """
        Get last synced commit SHA.

        Returns:
            Commit SHA string or None if not set
        """
        state = self.get_sync_state()
        return state.get("last_commit_sha")

    def set_last_commit_sha(self, sha: str) -> bool:
        """
        Update last synced commit SHA.

        Args:
            sha: GitHub commit SHA

        Returns:
            True if successful
        """
        return self.set_sync_state(last_commit_sha=sha)

    def get_sync_status(self) -> str:
        """Get current sync status."""
        state = self.get_sync_state()
        return state.get("sync_status", "idle")

    def set_sync_status(self, status: str) -> bool:
        """Update sync status (idle/syncing/failed)."""
        return self.set_sync_state(sync_status=status)

    def increment_synced_count(self) -> int:
        """Increment and return synced count."""
        try:
            new_count = self.client.hincrby(RedisKeys.SYNC_STATE, "synced_count", 1)
            return new_count
        except redis.RedisError as e:
            logger.error(f"Failed to increment sync count: {e}")
            return 0

    # ========================================================================
    # Changed Queue Operations
    # ========================================================================

    def add_changed_asset(self, asset_id: str) -> bool:
        """Add asset ID to changed queue."""
        try:
            self.client.rpush(RedisKeys.SYNC_CHANGED, asset_id)
            return True
        except redis.RedisError as e:
            logger.error(f"Failed to add changed asset {asset_id}: {e}")
            return False

    def get_changed_assets(self, count: int = 100) -> List[str]:
        """
        Get recent changed asset IDs.

        Args:
            count: Number of items to retrieve

        Returns:
            List of asset IDs
        """
        try:
            items = self.client.lrange(RedisKeys.SYNC_CHANGED, -count, -1)
            return list(reversed(items))  # Most recent first
        except redis.RedisError as e:
            logger.error(f"Failed to get changed assets: {e}")
            return []

    def trim_changed_assets(self, keep: int = 1000) -> bool:
        """
        Trim changed queue to keep only recent entries.

        Args:
            keep: Number of items to keep

        Returns:
            True if successful
        """
        try:
            self.client.ltrim(RedisKeys.SYNC_CHANGED, -keep, -1)
            return True
        except redis.RedisError as e:
            logger.error(f"Failed to trim changed assets: {e}")
            return False

    # ========================================================================
    # Utility Methods
    # ========================================================================

    def health_check(self) -> bool:
        """Check Redis connection health."""
        try:
            return self.client.ping()
        except redis.RedisError:
            return False

    def close(self) -> None:
        """Close Redis connection."""
        if self._client:
            self._client.close()
            self._client = None
            logger.info("Redis connection closed")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
