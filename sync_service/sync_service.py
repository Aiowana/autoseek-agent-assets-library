"""
Main synchronization service for assets.

Orchestrates the sync process between GitHub and Redis.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional, Set

from sync_service.config import Config, SyncConfig
from sync_service.github_manager import GitHubManager, Asset
from sync_service.models import StoredAsset
from sync_service.redis_client import RedisClient

logger = logging.getLogger(__name__)


# ============================================================================
# Sync Statistics
# ============================================================================

@dataclass
class SyncStats:
    """Statistics for a sync operation."""

    start_time: float
    end_time: Optional[float] = None
    total_processed: int = 0
    created: int = 0
    updated: int = 0
    deleted: int = 0
    failed: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        if self.end_time:
            return self.end_time - self.start_time
        return 0

    def to_dict(self) -> Dict:
        return {
            "start_time": datetime.fromtimestamp(self.start_time).isoformat(),
            "end_time": datetime.fromtimestamp(self.end_time).isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "total_processed": self.total_processed,
            "created": self.created,
            "updated": self.updated,
            "deleted": self.deleted,
            "failed": self.failed,
            "errors": self.errors[:10],  # Limit to first 10 errors
        }


# ============================================================================
# Main Sync Service
# ============================================================================

class AssetSyncService:
    """
    Main synchronization service for assets.

    Handles bidirectional sync between GitHub and Redis:
    - Read: Scan GitHub, parse manifests, store in Redis
    - Write: Push changes from UI back to GitHub
    """

    def __init__(
        self,
        config: Config,
        redis_client: RedisClient,
        github_manager: GitHubManager,
    ):
        """
        Initialize sync service.

        Args:
            config: Application configuration
            redis_client: Redis client wrapper
            github_manager: GitHub API wrapper
        """
        self.config = config
        self.redis = redis_client
        self.github = github_manager

    # ========================================================================
    # Read Sync (GitHub → Redis)
    # ========================================================================

    def sync_from_github(
        self,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> SyncStats:
        """
        Synchronize assets from GitHub to Redis.

        Args:
            progress_callback: Optional callback for progress updates
                Args: (current_description, current_count, total_count)

        Returns:
            SyncStats with operation results
        """
        import time

        stats = SyncStats(start_time=time.time())

        # Set sync status
        self.redis.set_sync_status("syncing")
        logger.info("Starting sync from GitHub to Redis")

        try:
            # Fetch all assets from GitHub
            github_assets = self.github.fetch_and_parse_all()
            total = len(github_assets)

            if progress_callback:
                progress_callback(f"Fetched {total} assets from GitHub", 0, total)

            # Get existing assets from Redis for comparison
            existing_assets = {asset.id: asset for asset in self.redis.get_all_assets()}
            existing_ids = set(existing_assets.keys())
            github_ids = {asset.id for asset in github_assets}

            # Track changes
            stats.total_processed = total

            for i, asset in enumerate(github_assets, 1):
                try:
                    should_update = self._should_update_asset(asset, existing_assets.get(asset.id))

                    if should_update:
                        stored_asset = asset.to_stored_asset()
                        old_category = existing_assets.get(asset.id).category if asset.id in existing_assets else None

                        success = self.redis.save_asset_atomic(stored_asset, old_category)

                        if success:
                            if asset.id not in existing_ids:
                                stats.created += 1
                                logger.debug(f"Created new asset: {asset.id}")
                            else:
                                stats.updated += 1
                                logger.debug(f"Updated asset: {asset.id}")

                            # Track changed asset
                            self.redis.add_changed_asset(asset.id)
                        else:
                            stats.failed += 1
                            stats.errors.append(f"Failed to save asset: {asset.id}")

                    if progress_callback:
                        progress_callback(f"Processed {asset.id}", i, total)

                except Exception as e:
                    stats.failed += 1
                    stats.errors.append(f"Error processing {asset.id}: {e}")
                    logger.error(f"Error processing asset {asset.id}: {e}")

            # Handle deleted assets (exist in Redis but not in GitHub)
            deleted_ids = existing_ids - github_ids
            if deleted_ids:
                stats.deleted = len(deleted_ids)
                for asset_id in deleted_ids:
                    try:
                        self.redis.delete_asset_atomic(asset_id)
                        logger.debug(f"Deleted asset: {asset_id}")
                    except Exception as e:
                        stats.errors.append(f"Failed to delete {asset_id}: {e}")

            # Update sync state
            now = int(time.time())
            self.redis.set_last_sync_time(now)
            self.redis.set_sync_state(synced_count=str(len(github_ids)))
            self.redis.trim_changed_assets(keep=1000)

            logger.info(f"Sync completed: {stats.created} created, {stats.updated} updated, {stats.deleted} deleted")

        except Exception as e:
            stats.errors.append(f"Sync failed: {e}")
            logger.error(f"Sync from GitHub failed: {e}")
            self.redis.set_sync_status("failed")
            raise

        finally:
            stats.end_time = time.time()
            if stats.failed == 0:
                self.redis.set_sync_status("idle")

        return stats

    def _should_update_asset(self, asset: Asset, existing: Optional[StoredAsset]) -> bool:
        """
        Determine if an asset should be updated in Redis.

        Args:
            asset: Asset from GitHub
            existing: Existing asset in Redis

        Returns:
            True if asset should be updated
        """
        if existing is None:
            return True

        # Update if SHA changed
        if existing.github_sha != asset.github_sha:
            return True

        # Update if version changed
        if existing.version != asset.version:
            return True

        return False

    # ========================================================================
    # Incremental Sync
    # ========================================================================

    def incremental_sync(self) -> SyncStats:
        """
        Perform incremental sync based on changes since last sync.

        Returns:
            SyncStats with operation results
        """
        import time

        stats = SyncStats(start_time=time.time())

        last_sync = self.redis.get_last_sync_time()
        if last_sync is None:
            logger.info("No previous sync found, performing full sync")
            return self.sync_from_github()

        logger.info(f"Performing incremental sync since {datetime.fromtimestamp(last_sync)}")

        # Get commits since last sync
        commits = self.github.get_commits_since(last_sync)

        if not commits:
            logger.info("No new commits since last sync")
            stats.end_time = time.time()
            return stats

        logger.info(f"Found {len(commits)} new commits, performing sync")
        return self.sync_from_github()

    # ========================================================================
    # Write Sync (UI → GitHub)
    # ========================================================================

    def create_asset(
        self,
        manifest_data: Dict,
        author: str,
        commit_message: Optional[str] = None,
    ) -> tuple[bool, str]:
        """
        Create a new asset in GitHub and sync to Redis.

        Args:
            manifest_data: Manifest data dictionary
            author: Author name for commit
            commit_message: Optional custom commit message

        Returns:
            Tuple of (success, message_or_url)
        """
        asset_id = manifest_data.get("id")
        if not asset_id:
            return False, "Asset ID is required"

        # Check if asset already exists
        if self.github.asset_exists_in_github(asset_id):
            return False, f"Asset {asset_id} already exists"

        # Generate commit message
        if commit_message is None:
            commit_message = f"Create asset: {asset_id}\n\nAuthor: {author}"

        # Save to GitHub
        success, result = self.github.save_to_github(
            asset_id=asset_id,
            manifest_data=manifest_data,
            commit_message=commit_message,
        )

        if not success:
            return False, result

        # Sync to Redis
        try:
            asset = self.github.get_asset_by_id(asset_id)
            if asset:
                stored_asset = asset.to_stored_asset()
                self.redis.save_asset_atomic(stored_asset)
                return True, result
        except Exception as e:
            logger.error(f"Failed to sync new asset to Redis: {e}")

        return True, result

    def update_asset(
        self,
        asset_id: str,
        manifest_data: Dict,
        author: str,
        commit_message: Optional[str] = None,
    ) -> tuple[bool, str]:
        """
        Update an existing asset in GitHub and sync to Redis.

        Args:
            asset_id: Asset identifier
            manifest_data: Updated manifest data
            author: Author name for commit
            commit_message: Optional custom commit message

        Returns:
            Tuple of (success, message_or_url)
        """
        # Get existing asset to find its path
        existing = self.github.get_asset_by_id(asset_id)
        if not existing:
            return False, f"Asset {asset_id} not found"

        # Generate commit message
        if commit_message is None:
            commit_message = f"Update asset: {asset_id}\n\nAuthor: {author}"

        # Update version
        manifest_data["version"] = self._increment_version(existing.manifest.version)

        # Save to GitHub
        success, result = self.github.save_to_github(
            asset_id=asset_id,
            manifest_data=manifest_data,
            commit_message=commit_message,
            target_path=existing.github_path,
        )

        if not success:
            return False, result

        # Sync to Redis
        try:
            asset = self.github.get_asset_by_id(asset_id)
            if asset:
                stored_asset = asset.to_stored_asset()
                old_category = existing.manifest.category
                self.redis.save_asset_atomic(stored_asset, old_category)
                return True, result
        except Exception as e:
            logger.error(f"Failed to sync updated asset to Redis: {e}")

        return True, result

    def delete_asset(
        self,
        asset_id: str,
        author: str,
        commit_message: Optional[str] = None,
    ) -> tuple[bool, str]:
        """
        Delete an asset from GitHub and Redis.

        Args:
            asset_id: Asset identifier
            author: Author name for commit
            commit_message: Optional custom commit message

        Returns:
            Tuple of (success, error_message if failed)
        """
        # Get existing asset
        existing = self.github.get_asset_by_id(asset_id)
        if not existing:
            return False, f"Asset {asset_id} not found"

        # Generate commit message
        if commit_message is None:
            commit_message = f"Delete asset: {asset_id}\n\nAuthor: {author}"

        # Delete from GitHub
        success, error = self.github.delete_from_github(
            asset_id=asset_id,
            file_path=existing.github_path,
            commit_message=commit_message,
        )

        if not success:
            return False, error

        # Delete from Redis
        try:
            self.redis.delete_asset_atomic(asset_id)
        except Exception as e:
            logger.error(f"Failed to delete asset from Redis: {e}")

        return True, ""

    @staticmethod
    def _increment_version(version: str) -> str:
        """Increment patch version."""
        parts = version.split(".")
        if len(parts) >= 3:
            parts[2] = str(int(parts[2]) + 1)
            return ".".join(parts)
        return version

    # ========================================================================
    # Query Operations
    # ========================================================================

    def get_asset(self, asset_id: str) -> Optional[StoredAsset]:
        """Get asset from Redis by ID."""
        return self.redis.get_asset(asset_id)

    def get_assets_by_category(self, category: str) -> List[StoredAsset]:
        """Get all assets in a category."""
        asset_ids = self.redis.get_by_category(category)
        assets = []
        for asset_id in asset_ids:
            asset = self.redis.get_asset(asset_id)
            if asset:
                assets.append(asset)
        return assets

    def list_categories(self) -> List[str]:
        """List all available categories."""
        return ["tool", "prompt", "skill"]

    # ========================================================================
    # Health Check
    # ========================================================================

    def health_check(self) -> Dict[str, bool]:
        """Check health of all services."""
        return {
            "redis": self.redis.health_check(),
            "github": self._check_github_connection(),
        }

    def _check_github_connection(self) -> bool:
        """Check GitHub API connection."""
        try:
            self.github.repo.get_branch(self.github.config.branch)
            return True
        except Exception:
            return False
