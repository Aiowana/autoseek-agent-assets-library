"""
Webhook 事件处理器

处理接收到的 GitHub Webhook 事件，并触发相应的同步操作。
"""

import asyncio
import logging
from typing import Dict, Any, Optional

from sync_service.webhook.models import WebhookEvent, SyncTrigger

logger = logging.getLogger(__name__)


class WebhookHandler:
    """
    Webhook 事件处理器

    负责解析 Webhook 事件并决定是否触发同步。
    """

    def __init__(self, sync_service, target_branch: str = "main"):
        """
        初始化处理器

        Args:
            sync_service: AssetSyncService 实例
            target_branch: 目标分支名，只有该分支的推送才会触发同步
        """
        self.sync_service = sync_service
        self.target_branch = target_branch

    async def handle_event(self, event: WebhookEvent) -> Dict[str, Any]:
        """
        处理 Webhook 事件

        Args:
            event: 解析后的 Webhook 事件

        Returns:
            处理结果字典
        """
        event_type = event.event_type

        # 记录事件
        logger.info(
            f"Webhook received: type={event_type}, delivery={event.delivery_id}"
        )

        # 处理不同类型的事件
        if event_type == "ping":
            return self._handle_ping(event)

        elif event_type == "push":
            return await self._handle_push(event)

        else:
            logger.info(f"Unsupported event type: {event_type}")
            return {
                "status": "ignored",
                "reason": f"unsupported_event_type",
                "event_type": event_type,
            }

    def _handle_ping(self, event: WebhookEvent) -> Dict[str, Any]:
        """处理 Ping 事件"""
        logger.info("Ping received, responding with pong")
        return {"status": "ok", "message": "pong"}

    async def _handle_push(self, event: WebhookEvent) -> Dict[str, Any]:
        """处理 Push 事件"""
        push_event = event.as_push_event()
        if not push_event:
            return {
                "status": "error",
                "reason": "invalid_push_event",
            }

        branch = push_event.branch
        commit_sha = push_event.after

        # 检查是否是目标分支
        if branch != self.target_branch:
            logger.info(
                f"Push to non-target branch: {branch} (target: {self.target_branch}), ignoring"
            )
            return {
                "status": "ignored",
                "reason": "branch_not_matched",
                "branch": branch,
                "target_branch": self.target_branch,
            }

        # 检查是否是删除分支
        if commit_sha == "0000000000000000000000000000000000000000":
            logger.info(f"Branch deletion detected: {branch}, ignoring")
            return {
                "status": "ignored",
                "reason": "branch_deletion",
                "branch": branch,
            }

        # 触发同步
        logger.info(
            f"Push to target branch detected: {branch}, commit={commit_sha}, triggering sync"
        )

        # 异步触发同步，不阻塞响应
        asyncio.create_task(self._trigger_sync(
            trigger=SyncTrigger(
                source="webhook",
                event_type="push",
                delivery_id=event.delivery_id,
                commit_sha=commit_sha,
            )
        ))

        return {
            "status": "triggered",
            "branch": branch,
            "commit_sha": commit_sha,
            "delivery_id": event.delivery_id,
        }

    async def _trigger_sync(self, trigger: SyncTrigger):
        """异步执行同步"""
        try:
            logger.info(f"Sync triggered by: {trigger.to_dict()}")

            # 执行增量同步
            stats = self.sync_service.incremental_sync()

            logger.info(
                f"Sync completed: created={stats.created}, "
                f"updated={stats.updated}, deleted={stats.deleted}, "
                f"failed={stats.failed}, skipped={stats.skipped}"
            )

        except Exception as e:
            logger.error(f"Sync failed: {e}", exc_info=True)


def create_handler(sync_service, target_branch: str = "main") -> WebhookHandler:
    """创建 Webhook 处理器"""
    return WebhookHandler(sync_service, target_branch)
