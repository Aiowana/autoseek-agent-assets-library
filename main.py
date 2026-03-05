#!/usr/bin/env python3
"""
Agent Asset Library Sync Service - Main Entry Point

Usage:
    # One-time sync
    python main.py sync

    # Continuous sync with polling
    python main.py sync --continuous

    # Health check
    python main.py health

    # List assets
    python main.py list

    # Get asset details
    python main.py get <asset_id>

    # View global index
    python main.py index
"""

import argparse
import sys
from pathlib import Path

from sync_service import Config, setup_logging, Logger, RedisClient, GitHubManager, ManifestValidator, AssetSyncService
from sync_service.webhook.server import create_app
from sync_service.webhook.handler import create_handler
from sync_service.tenant import TenantManager, TenantConfig, get_tenant_manager, init_tenant_manager
from sync_service.webhook.multi_tenant_server import create_multi_tenant_app

# Setup colored logging
setup_logging(level="INFO", use_colors=True)

# Create logger
logger = Logger(__name__)


# ============================================================================
# Configuration
# ============================================================================

def load_config(config_path: str = None) -> Config:
    """Load configuration from file or environment variables."""
    if config_path and Path(config_path).exists():
        config = Config.from_yaml(config_path)
    else:
        config = Config.from_env()

    if config_path and Path(config_path).exists():
        logger.info(f"Loading configuration from: {config_path}")
    else:
        logger.info("Loading configuration from environment variables")

    return config


def load_tenants(tenants_config_path: str = None) -> TenantManager:
    """Load tenant configuration from file."""
    if tenants_config_path and Path(tenants_config_path).exists():
        return init_tenant_manager(tenants_config_path)
    else:
        # 尝试默认路径
        default_paths = ["tenants.yaml", "config/tenants.yaml"]
        for path in default_paths:
            if Path(path).exists():
                logger.info(f"Loading tenant configuration from: {path}")
                return init_tenant_manager(path)
        logger.info("No tenant configuration found, using empty tenant manager")
        return get_tenant_manager()


def initialize_service(config: Config, namespace: str = "default") -> AssetSyncService:
    """
    Initialize the sync service with all dependencies.

    Args:
        config: Application configuration
        namespace: 租户命名空间 (默认: "default")
    """
    redis_client = RedisClient(config.redis, namespace=namespace)
    validator = ManifestValidator()
    github_manager = GitHubManager(config.github, validator)
    sync_service = AssetSyncService(config, redis_client, github_manager)

    return sync_service


# ============================================================================
# Commands
# ============================================================================

def cmd_sync(args, config: Config):
    """Execute sync from GitHub to Redis."""
    tenant_manager = load_tenants(args.tenants_config)

    # 检查是否是多租户模式
    if args.all:
        # 同步所有启用的租户
        tenants = tenant_manager.list_tenants(enabled_only=True)
        if not tenants:
            logger.warning("No enabled tenants found")
            return 1

        logger.info(f"Syncing {len(tenants)} tenants")

        total_created = 0
        total_updated = 0
        total_deleted = 0
        total_failed = 0

        for tenant in tenants:
            logger.info(f"Syncing tenant: {tenant.namespace} ({tenant.name})")
            try:
                # 为每个租户创建服务
                tenant_config = tenant_manager.get_tenant(tenant.namespace)
                sync_service = _create_service_for_tenant(config, tenant_config)

                stats = sync_service.sync_from_github(
                    progress_callback=None,
                    use_lock=True,
                )

                total_created += stats.created
                total_updated += stats.updated
                total_deleted += stats.deleted
                total_failed += stats.failed

                logger.info(
                    f"  Tenant {tenant.namespace}: {stats.created} created, "
                    f"{stats.updated} updated, {stats.deleted} deleted"
                )

            except Exception as e:
                logger.error(f"Failed to sync tenant {tenant.namespace}: {e}")
                total_failed += 1

        logger.info("=" * 50)
        logger.info("Overall Sync Summary")
        logger.info("=" * 50)
        logger.info(f"Total created: {total_created}")
        logger.info(f"Total updated: {total_updated}")
        logger.info(f"Total deleted: {total_deleted}")
        logger.info(f"Total failed: {total_failed}")

        return 0 if total_failed == 0 else 1

    elif args.tenant:
        # 同步指定租户
        tenant = tenant_manager.get_tenant(args.tenant)
        if not tenant:
            logger.error(f"Tenant not found: {args.tenant}")
            return 1

        if not tenant.enabled:
            logger.error(f"Tenant disabled: {args.tenant}")
            return 1

        logger.info(f"Syncing tenant: {tenant.namespace} ({tenant.name})")
        service = _create_service_for_tenant(config, tenant)
        namespace = tenant.namespace

    else:
        # 单租户模式（默认）
        service = initialize_service(config)
        namespace = "default"

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
        logger.info(f"Namespace: {namespace}")
        logger.info(f"Duration: {stats.duration_seconds:.2f}s")

        if getattr(stats, 'skipped', False):
            logger.info("Status: Skipped (no changes detected)")
        else:
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


def _create_service_for_tenant(config: Config, tenant: TenantConfig) -> AssetSyncService:
    """
    为指定租户创建同步服务

    Args:
        config: 基础配置
        tenant: 租户配置

    Returns:
        AssetSyncService 实例
    """
    from sync_service.config import GitHubConfig

    redis_client = RedisClient(config.redis, namespace=tenant.namespace)
    validator = ManifestValidator()

    github_config = GitHubConfig(
        token=tenant.git_token,
        repo=tenant.git_repo,
        branch=tenant.git_branch,
    )
    github_manager = GitHubManager(github_config, validator)

    return AssetSyncService(config, redis_client, github_manager)


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


def cmd_index(args, config: Config):
    """Get global lightweight index of all assets."""
    service = initialize_service(config)

    index = service.get_global_index()

    if args.json:
        import json
        print(json.dumps(index, ensure_ascii=False, indent=2))
    else:
        logger.info(f"Global index: {len(index)} assets")
        print("-" * 60)
        for asset_id, data in index.items():
            print(f"  [{data['category']}] {asset_id}")
            print(f"      Name: {data['name']}")
            print(f"      Version: {data['version']}")
            if data.get('description'):
                desc = data['description'][:50] + "..." if len(data['description']) > 50 else data['description']
                print(f"      Description: {desc}")
            print()

    return 0


def cmd_serve(args, config: Config):
    """Start the Webhook server."""
    # 加载租户管理器
    tenant_manager = load_tenants(args.tenants_config)

    # 检查是否使用多租户模式
    if args.multi_tenant:
        # 多租户模式
        app = create_multi_tenant_app(config, tenant_manager)

        status = tenant_manager.get_status()
        logger.info(f"Starting multi-tenant webhook server with {status['enabled_tenants']} tenants")
    else:
        # 单租户模式
        sync_service_instance = initialize_service(config)
        app = create_app(config)
        handler = create_handler(sync_service_instance, target_branch=config.github.branch)

        import sync_service.webhook.server as webhook_server
        webhook_server.set_handler(handler)
        logger.info("Starting single-tenant webhook server")

    # 启动服务器
    import uvicorn

    host = args.host or config.webhook.host
    port = args.port or config.webhook.port

    logger.info(f"Starting webhook server on {host}:{port}")
    logger.info(f"Multi-tenant mode: {args.multi_tenant}")
    logger.info(f"Signature verification: {'enabled' if config.webhook.secret else 'disabled'}")

    try:
        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level="info",
        )
    except KeyboardInterrupt:
        logger.info("Webhook server stopped by user")
        return 0
    except Exception as e:
        logger.error(f"Webhook server error: {e}", exc_info=True)
        return 1


def cmd_tenants(args, config: Config):
    """List all tenants."""
    tenant_manager = load_tenants(args.tenants_config)
    tenants = tenant_manager.list_tenants(enabled_only=not args.all)

    if not tenants:
        logger.info("No tenants found")
        return 0

    logger.info(f"Tenants ({len(tenants)}):")
    print("-" * 60)
    for tenant in tenants:
        status = "enabled" if tenant.enabled else "disabled"
        print(f"  {tenant.namespace:30} {tenant.name:20} [{status}]")
        print(f"    Platform: {tenant.git_platform}")
        print(f"    Repo: {tenant.git_repo}")
        print(f"    Branch: {tenant.git_branch}")
        print(f"    Webhook: {tenant.get_webhook_path()}")
        print()

    return 0


def cmd_tenant_add(args, config: Config):
    """Add a new tenant."""
    tenant_manager = load_tenants(args.tenants_config)

    # 检查命名空间格式
    if not tenant_manager.validate_namespace(args.namespace):
        logger.error(f"Invalid namespace format: {args.namespace}")
        logger.error("Namespace must start with proj_, user_, org_, or env_ and contain only lowercase letters, numbers, and underscores")
        return 1

    # 检查是否已存在
    if tenant_manager.get_tenant(args.namespace):
        logger.error(f"Tenant already exists: {args.namespace}")
        return 1

    # 获取环境变量中的敏感信息
    import os
    git_token = os.getenv(args.git_token) if args.git_token else ""
    webhook_secret = os.getenv(args.webhook_secret) if args.webhook_secret else ""

    if not git_token:
        logger.error(f"Git token not found (env var: {args.git_token})")
        return 1

    # 创建租户配置
    tenant = TenantConfig(
        namespace=args.namespace,
        name=args.name,
        git_platform=args.platform,
        git_token=git_token,
        git_repo=args.repo,
        git_branch=args.branch,
        webhook_secret=webhook_secret,
        enabled=True,
    )

    # 添加租户
    if tenant_manager.add_tenant(tenant):
        logger.info(f"Added tenant: {tenant.namespace} ({tenant.name})")

        # 保存到配置文件
        if args.save:
            _save_tenants_to_file(tenant_manager, args.tenants_config)
            logger.info(f"Saved tenant configuration to: {args.tenants_config}")

        return 0
    else:
        logger.error(f"Failed to add tenant: {args.namespace}")
        return 1


def cmd_tenant_remove(args, config: Config):
    """Remove a tenant."""
    tenant_manager = load_tenants(args.tenants_config)

    if not tenant_manager.get_tenant(args.namespace):
        logger.error(f"Tenant not found: {args.namespace}")
        return 1

    # 确认删除
    if not args.force:
        response = input(f"Are you sure you want to remove tenant '{args.namespace}'? (y/N): ")
        if response.lower() != 'y':
            logger.info("Cancelled")
            return 0

    if tenant_manager.remove_tenant(args.namespace):
        logger.info(f"Removed tenant: {args.namespace}")

        # 保存到配置文件
        if args.save:
            _save_tenants_to_file(tenant_manager, args.tenants_config)
            logger.info(f"Updated tenant configuration in: {args.tenants_config}")

        return 0
    else:
        logger.error(f"Failed to remove tenant: {args.namespace}")
        return 1


def _save_tenants_to_file(tenant_manager: TenantManager, config_path: str):
    """保存租户配置到文件"""
    import yaml
    from pathlib import Path

    tenants = tenant_manager.list_tenants()
    data = {
        "tenants": [
            {
                "namespace": t.namespace,
                "name": t.name,
                "git_platform": t.git_platform,
                "git_token": f"${{{t.namespace.upper()}_GITHUB_TOKEN}}",
                "git_repo": t.git_repo,
                "git_branch": t.git_branch,
                "webhook_secret": f"${{{t.namespace.upper()}_WEBHOOK_SECRET}}",
                "enabled": t.enabled,
            }
            for t in tenants
        ]
    }

    config_file = Path(config_path)
    config_file.parent.mkdir(parents=True, exist_ok=True)

    with open(config_file, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


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
        "--tenants-config", "-t",
        type=str,
        default="tenants.yaml",
        help="Path to tenants configuration file (default: tenants.yaml)",
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
    sync_parser.add_argument(
        "--tenant", "-n",
        type=str,
        help="Sync specific tenant by namespace",
    )
    sync_parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Sync all enabled tenants",
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

    # Index command
    index_parser = subparsers.add_parser("index", help="Get global lightweight index")
    index_parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output as JSON",
    )

    # Serve command
    serve_parser = subparsers.add_parser("serve", help="Start webhook server")
    serve_parser.add_argument(
        "--host",
        type=str,
        help=f"Host to bind to (default: from config or 0.0.0.0)",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        help=f"Port to bind to (default: from config or 8080)",
    )
    serve_parser.add_argument(
        "--multi-tenant", "-m",
        action="store_true",
        help="Enable multi-tenant mode",
    )

    # Tenants command
    tenants_parser = subparsers.add_parser("tenants", help="List all tenants")
    tenants_parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="List all tenants including disabled ones",
    )

    # Tenant add command
    tenant_add_parser = subparsers.add_parser("tenant-add", help="Add a new tenant")
    tenant_add_parser.add_argument("namespace", type=str, help="Tenant namespace (e.g., proj_alpha)")
    tenant_add_parser.add_argument("name", type=str, help="Tenant name")
    tenant_add_parser.add_argument("--platform", type=str, default="github", choices=["github", "gitee"], help="Git platform")
    tenant_add_parser.add_argument("--repo", type=str, required=True, help="Repository (owner/repo)")
    tenant_add_parser.add_argument("--branch", type=str, default="main", help="Branch name")
    tenant_add_parser.add_argument("--git-token", type=str, required=True, help="Environment variable name for Git token")
    tenant_add_parser.add_argument("--webhook-secret", type=str, default="", help="Environment variable name for webhook secret")
    tenant_add_parser.add_argument("--save", action="store_true", help="Save to tenants configuration file")

    # Tenant remove command
    tenant_remove_parser = subparsers.add_parser("tenant-remove", help="Remove a tenant")
    tenant_remove_parser.add_argument("namespace", type=str, help="Tenant namespace")
    tenant_remove_parser.add_argument("--force", "-f", action="store_true", help="Skip confirmation")
    tenant_remove_parser.add_argument("--save", action="store_true", help="Update tenants configuration file")

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
        "index": cmd_index,
        "serve": cmd_serve,
        "tenants": cmd_tenants,
        "tenant-add": cmd_tenant_add,
        "tenant-remove": cmd_tenant_remove,
    }

    handler = command_handlers.get(args.command)
    if handler:
        return handler(args, config)
    else:
        logger.error(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
