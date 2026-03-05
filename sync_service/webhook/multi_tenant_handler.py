"""
多租户 Webhook 事件处理器

处理接收到的 GitHub/Gitee Webhook 事件，按租户触发相应的同步操作。
"""

import asyncio
import logging
from typing import Any, Dict, Optional

from sync_service.webhook.models import WebhookEvent, SyncTrigger
from sync_service.tenant import TenantManager, TenantConfig
from sync_service.sync_service import AssetSyncService
from sync_service.redis_client import RedisClient
from sync_service.github_manager import GitHubManager
from sync_service.config import Config, RedisConfig, GitHubConfig
from sync_service.schema import ManifestValidator

logger = logging.getLogger(__name__)


class MultiTenantWebhookHandler:
    """
    多租户 Webhook 事件处理器

    负责解析 Webhook 事件并按租户触发同步。
    """

    def __init__(
        self,
        tenant_manager: TenantManager,
        base_config: Config,
    ):
        """
        初始化处理器

        Args:
            tenant_manager: 租户管理器
            base_config: 基础配置 (用于 Redis 等共享组件)
        """
        self.tenant_manager = tenant_manager
        self.base_config = base_config
        self._sync_services: Dict[str, AssetSyncService] = {}
        self._validator = ManifestValidator()

    async def handle_event(
        self,
        namespace: str,
        event: WebhookEvent
    ) -> Dict[str, Any]:
        """
        处理 Webhook 事件

        Args:
            namespace: 租户命名空间
            event: 解析后的 Webhook 事件

        Returns:
            处理结果字典
        """
        # 检查租户是否存在
        tenant = self.tenant_manager.get_tenant(namespace)
        if not tenant:
            logger.warning(f"Tenant not found: {namespace}")
            return {
                "status": "error",
                "reason": "tenant_not_found",
                "namespace": namespace,
            }

        # 检查租户是否启用
        if not tenant.enabled:
            logger.warning(f"Tenant disabled: {namespace}")
            return {
                "status": "ignored",
                "reason": "tenant_disabled",
                "namespace": namespace,
            }

        event_type = event.event_type

        # 记录事件
        logger.info(
            f"Webhook received for {namespace}: type={event_type}, delivery={event.delivery_id}"
        )

        # 处理不同类型的事件
        if event_type == "ping":
            return self._handle_ping(namespace, event)

        elif event_type == "push":
            return await self._handle_push(namespace, tenant, event)

        else:
            logger.info(f"Unsupported event type: {event_type}")
            return {
                "status": "ignored",
                "reason": "unsupported_event_type",
                "event_type": event_type,
                "namespace": namespace,
            }

    def _handle_ping(self, namespace: str, event: WebhookEvent) -> Dict[str, Any]:
        """处理 Ping 事件"""
        logger.info(f"Ping received for {namespace}, responding with pong")
        return {
            "status": "ok",
            "message": "pong",
            "namespace": namespace,
        }

    async def _handle_push(
        self,
        namespace: str,
        tenant: TenantConfig,
        event: WebhookEvent
    ) -> Dict[str, Any]:
        """处理 Push 事件"""
        push_event = event.as_push_event()
        if not push_event:
            return {
                "status": "error",
                "reason": "invalid_push_event",
                "namespace": namespace,
            }

        branch = push_event.branch
        commit_sha = push_event.after

        # 检查是否是目标分支
        if branch != tenant.git_branch:
            logger.info(
                f"Push to non-target branch: {branch} (target: {tenant.git_branch}), ignoring"
            )
            return {
                "status": "ignored",
                "reason": "branch_not_matched",
                "branch": branch,
                "target_branch": tenant.git_branch,
                "namespace": namespace,
            }

        # 检查是否是删除分支
        if commit_sha == "0000000000000000000000000000000000000000":
            logger.info(f"Branch deletion detected: {branch}, ignoring")
            return {
                "status": "ignored",
                "reason": "branch_deletion",
                "branch": branch,
                "namespace": namespace,
            }

        # 触发同步
        logger.info(
            f"Push to target branch detected: {branch}, commit={commit_sha}, triggering sync for {namespace}"
        )

        # 异步触发同步，不阻塞响应
        asyncio.create_task(self._trigger_sync(
            namespace=namespace,
            tenant=tenant,
            trigger=SyncTrigger(
                source="webhook",
                event_type="push",
                delivery_id=event.delivery_id,
                commit_sha=commit_sha,
            )
        ))

        return {
            "status": "triggered",
            "namespace": namespace,
            "branch": branch,
            "commit_sha": commit_sha,
            "delivery_id": event.delivery_id,
        }

    async def _trigger_sync(
        self,
        namespace: str,
        tenant: TenantConfig,
        trigger: SyncTrigger
    ):
        """异步执行同步"""
        try:
            logger.info(f"Sync triggered for {namespace}: {trigger.to_dict()}")

            # 获取或创建租户的同步服务
            sync_service = self._get_or_create_sync_service(tenant)

            # 执行增量同步
            stats = sync_service.incremental_sync()

            logger.info(
                f"Sync completed for {namespace}: created={stats.created}, "
                f"updated={stats.updated}, deleted={stats.deleted}, "
                f"failed={stats.failed}, skipped={stats.skipped}"
            )

        except Exception as e:
            logger.error(f"Sync failed for {namespace}: {e}", exc_info=True)

    def _get_or_create_sync_service(self, tenant: TenantConfig) -> AssetSyncService:
        """
        获取或创建租户的同步服务

        Args:
            tenant: 租户配置

        Returns:
            AssetSyncService 实例
        """
        # 如果已缓存，直接返回
        if tenant.namespace in self._sync_services:
            return self._sync_services[tenant.namespace]

        # 创建新的 Redis 客户端（使用租户命名空间）
        redis_client = RedisClient(self.base_config.redis, namespace=tenant.namespace)

        # 创建新的 GitHub 管理器（使用租户的 Token 和仓库）
        github_config = GitHubConfig(
            token=tenant.git_token,
            repo=tenant.git_repo,
            branch=tenant.git_branch,
        )
        github_manager = GitHubManager(github_config, self._validator)

        # 创建同步服务
        sync_service = AssetSyncService(
            self.base_config,
            redis_client,
            github_manager,
        )

        # 缓存服务实例
        self._sync_services[tenant.namespace] = sync_service

        logger.info(f"Created sync service for tenant: {tenant.namespace}")
        return sync_service

    def clear_cache(self, namespace: Optional[str] = None):
        """
        清除同步服务缓存

        Args:
            namespace: 指定命名空间，None 表示清除所有
        """
        if namespace:
            if namespace in self._sync_services:
                del self._sync_services[namespace]
                logger.info(f"Cleared sync service cache for: {namespace}")
        else:
            self._sync_services.clear()
            logger.info("Cleared all sync service cache")


def create_multi_tenant_handler(
    tenant_manager: TenantManager,
    base_config: Config,
) -> MultiTenantWebhookHandler:
    """创建多租户 Webhook 处理器"""
    return MultiTenantWebhookHandler(tenant_manager, base_config)
