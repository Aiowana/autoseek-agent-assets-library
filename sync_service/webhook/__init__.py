"""
Webhook 模块 - 接收和处理 GitHub/Gitee Webhook 事件

本模块提供 FastAPI 服务器，用于接收 GitHub/Gitee 发送的 Webhook 事件，
验证签名，并触发相应的同步操作。

支持单租户和多租户两种模式。
"""

# 单租户模式
from sync_service.webhook.server import create_app, set_handler

# 多租户模式
from sync_service.webhook.multi_tenant_server import create_multi_tenant_app, get_multi_tenant_handler
from sync_service.webhook.multi_tenant_handler import (
    MultiTenantWebhookHandler,
    create_multi_tenant_handler,
)

# 共享组件
from sync_service.webhook.models import WebhookEvent, SyncTrigger
from sync_service.webhook.verifier import WebhookVerifier
from sync_service.webhook.handler import WebhookHandler, create_handler

__all__ = [
    # 单租户模式
    "create_app",
    "set_handler",
    "create_handler",
    "WebhookHandler",
    # 多租户模式
    "create_multi_tenant_app",
    "get_multi_tenant_handler",
    "create_multi_tenant_handler",
    "MultiTenantWebhookHandler",
    # 共享组件
    "WebhookEvent",
    "SyncTrigger",
    "WebhookVerifier",
]
