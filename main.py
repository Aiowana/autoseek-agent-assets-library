#!/usr/bin/env python3
"""
Agent Asset Library Sync Service - Main Entry Point

Usage:
    # One-time sync
    python main.py sync

    # Continuous sync with polling
    python main.py sync --continuous

    # Create a new asset
    python main.py create <manifest.yaml>

    # Health check
    python main.py health

    # Server mode (future: HTTP API)
    python main.py server
"""

import argparse
import logging
import sys
from pathlib import Path

from sync_service import Config, RedisClient, GitHubManager, ManifestValidator, AssetSyncService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================================
# Configuration
# ============================================================================

def load_config(config_path: str = None) -> Config:
    """Load configuration from file or environment variables."""
    if config_path and Path(config_path).exists():
        logger.info(f"Loading configuration from: {config_path}")
        config = Config.from_yaml(config_path)
    else:
        logger.info("Loading configuration from environment variables")
        config = Config.from_env()

    config.setup_logging()
    return config


def initialize_service(config: Config) -> AssetSyncService:
    """Initialize the sync service with all dependencies."""
    redis_client = RedisClient(config.redis)
    validator = ManifestValidator()
    github_manager = GitHubManager(config.github, validator)
    sync_service = AssetSyncService(config, redis_client, github_manager)

    return sync_service


# ============================================================================
# Commands
# ============================================================================

def cmd_sync(args, config: Config):
    """Execute sync from GitHub to Redis."""
    service = initialize_service(config)

    logger.info("=" * 50)
    logger.info("Starting sync from GitHub to Redis")
    logger.info("=" * 50)

    def progress_callback(description: str, current: int, total: int):
        if args.verbose:
            logger.info(f"[{current}/{total}] {description}")

    try:
        if args.incremental:
            stats = service.incremental_sync()
        else:
            stats = service.sync_from_github(
                progress_callback=progress_callback if args.verbose else None,
            )

        # Print summary
        logger.info("=" * 50)
        logger.info("Sync Summary")
        logger.info("=" * 50)
        logger.info(f"Duration: {stats.duration_seconds:.2f}s")
        logger.info(f"Total processed: {stats.total_processed}")
        logger.info(f"Created: {stats.created}")
        logger.info(f"Updated: {stats.updated}")
        logger.info(f"Deleted: {stats.deleted}")
        logger.info(f"Failed: {stats.failed}")

        if stats.errors:
            logger.warning(f"Errors encountered: {len(stats.errors)}")
            for error in stats.errors[:5]:
                logger.warning(f"  - {error}")

        return 0 if stats.failed == 0 else 1

    except Exception as e:
        logger.error(f"Sync failed: {e}", exc_info=True)
        return 1


def cmd_continuous(args, config: Config):
    """Run continuous sync with polling."""
    service = initialize_service(config)
    import time

    interval = config.sync.interval_seconds
    logger.info(f"Starting continuous sync (interval: {interval}s)")

    try:
        while True:
            logger.info("Running scheduled sync...")
            stats = service.sync_from_github()

            logger.info(
                f"Sync completed: {stats.created} created, {stats.updated} updated, "
                f"{stats.deleted} deleted, {stats.failed} failed"
            )

            logger.info(f"Next sync in {interval}s...")
            time.sleep(interval)

    except KeyboardInterrupt:
        logger.info("Continuous sync stopped by user")
        return 0


def cmd_health(args, config: Config):
    """Check health of all services."""
    service = initialize_service(config)

    health = service.health_check()

    print("Health Check Results:")
    print("-" * 30)
    for service_name, status in health.items():
        status_str = "OK" if status else "FAILED"
        print(f"  {service_name}: {status_str}")

    all_ok = all(health.values())
    return 0 if all_ok else 1


def cmd_list(args, config: Config):
    """List assets in storage."""
    service = initialize_service(config)

    if args.category:
        assets = service.get_assets_by_category(args.category)
        logger.info(f"Assets in category '{args.category}': {len(assets)}")
    else:
        assets = service.redis.get_all_assets()
        logger.info(f"Total assets: {len(assets)}")

    for asset in assets:
        print(f"  [{asset.category}] {asset.id} - {asset.name} (v{asset.version})")

    return 0


def cmd_get(args, config: Config):
    """Get details of a specific asset."""
    service = initialize_service(config)

    asset = service.get_asset(args.asset_id)
    if not asset:
        logger.error(f"Asset not found: {args.asset_id}")
        return 1

    print(f"Asset: {asset.id}")
    print(f"  Name: {asset.name}")
    print(f"  Version: {asset.version}")
    print(f"  Category: {asset.category}")
    print(f"  Description: {asset.description}")
    print(f"  GitHub Path: {asset.github_path}")
    print(f"  GitHub SHA: {asset.github_sha}")

    return 0


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Agent Asset Library Sync Service",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--config", "-c",
        type=str,
        default="settings.yaml",
        help="Path to configuration file (default: settings.yaml)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Sync command
    sync_parser = subparsers.add_parser("sync", help="Synchronize assets from GitHub")
    sync_parser.add_argument(
        "--incremental", "-i",
        action="store_true",
        help="Perform incremental sync (since last sync)",
    )
    sync_parser.add_argument(
        "--continuous",
        action="store_true",
        help="Run continuous sync with polling",
    )

    # Health command
    subparsers.add_parser("health", help="Check service health")

    # List command
    list_parser = subparsers.add_parser("list", help="List assets")
    list_parser.add_argument(
        "--category", "-c",
        type=str,
        choices=["tool", "prompt", "skill"],
        help="Filter by category",
    )

    # Get command
    get_parser = subparsers.add_parser("get", help="Get asset details")
    get_parser.add_argument("asset_id", type=str, help="Asset ID")

    # Parse arguments
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Load configuration
    try:
        config = load_config(args.config)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        return 1

    # Execute command
    command_handlers = {
        "sync": cmd_sync,
        "health": cmd_health,
        "list": cmd_list,
        "get": cmd_get,
    }

    handler = command_handlers.get(args.command)
    if handler:
        return handler(args, config)
    else:
        logger.error(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
