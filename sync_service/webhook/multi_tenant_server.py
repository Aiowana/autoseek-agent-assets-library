"""
多租户 Webhook HTTP 服务器

使用 FastAPI 提供 HTTP 服务，接收 GitHub/Gitee Webhook 请求。
支持动态路由 /webhook/{platform}/{namespace}，按租户验证签名并触发同步。
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import JSONResponse

from sync_service.config import Config
from sync_service.webhook.models import WebhookEvent
from sync_service.webhook.verifier import WebhookVerifier
from sync_service.webhook.multi_tenant_handler import MultiTenantWebhookHandler
from sync_service.tenant import get_tenant_manager, TenantManager

logger = logging.getLogger(__name__)

# 全局变量
_multi_tenant_handler: Optional[MultiTenantWebhookHandler] = None
_app_state: Dict[str, Any] = {}


def create_multi_tenant_app(
    config: Config,
    tenant_manager: Optional[TenantManager] = None,
) -> FastAPI:
    """
    创建多租户 FastAPI 应用

    Args:
        config: 应用配置
        tenant_manager: 租户管理器（可选，默认使用全局实例）

    Returns:
        FastAPI 应用实例
    """
    global _multi_tenant_handler

    # 使用传入的租户管理器或获取全局实例
    if tenant_manager is None:
        tenant_manager = get_tenant_manager()

    app = FastAPI(
        title="Agent Asset Library Multi-Tenant Webhook Server",
        description="多租户 Webhook 服务器，接收 GitHub/Gitee 事件并触发资产同步",
        version="2.0.0",
    )

    # 初始化多租户处理器
    _multi_tenant_handler = MultiTenantWebhookHandler(tenant_manager, config)
    logger.info("Multi-tenant webhook handler initialized")

    # 初始化状态
    _app_state["start_time"] = datetime.now()
    _app_state["total_received"] = 0
    _app_state["last_received"] = None
    _app_state["by_namespace"] = {}

    @app.on_event("startup")
    async def startup():
        """应用启动时的初始化"""
        logger.info(f"Multi-tenant webhook server starting on {config.webhook.host}:{config.webhook.port}")
        status = tenant_manager.get_status()
        logger.info(f"Tenants loaded: {status['total_tenants']} total, {status['enabled_tenants']} enabled")

    @app.on_event("shutdown")
    async def shutdown():
        """应用关闭时的清理"""
        logger.info("Multi-tenant webhook server shutting down")

    @app.get("/")
    async def root():
        """根路径"""
        return {
            "service": "Agent Asset Library Multi-Tenant Webhook Server",
            "status": "running",
            "version": "2.0.0",
            "mode": "multi-tenant",
        }

    @app.get("/health")
    async def health():
        """健康检查"""
        return {
            "status": "healthy",
            "mode": "multi-tenant",
            "uptime_seconds": (datetime.now() - _app_state["start_time"]).total_seconds(),
        }

    @app.get("/webhook/status")
    async def webhook_status():
        """Webhook 状态查询"""
        status = tenant_manager.get_status()
        return {
            "mode": "multi-tenant",
            "tenants": status,
            "stats": {
                "total_received": _app_state["total_received"],
                "last_received": _app_state["last_received"].isoformat() if _app_state["last_received"] else None,
                "by_namespace": _app_state["by_namespace"],
            },
        }

    @app.get("/webhook/status/{namespace}")
    async def namespace_webhook_status(namespace: str):
        """查询指定租户的 Webhook 状态"""
        tenant = tenant_manager.get_tenant(namespace)
        if not tenant:
            raise HTTPException(status_code=404, detail=f"Tenant not found: {namespace}")

        return {
            "namespace": namespace,
            "name": tenant.name,
            "enabled": tenant.enabled,
            "platform": tenant.git_platform,
            "repo": tenant.git_repo,
            "branch": tenant.git_branch,
            "webhook_path": tenant.get_webhook_path(),
            "stats": _app_state["by_namespace"].get(namespace, {}),
        }

    @app.post("/webhook/{platform}/{namespace}")
    async def multi_tenant_webhook(platform: str, namespace: str, request: Request):
        """
        多租户 Webhook 接收端点

        接收 GitHub/Gitee 发送的 Webhook 事件，按租户验证签名并触发相应的操作。

        Args:
            platform: 平台类型 (github, gitee)
            namespace: 租户命名空间
        """
        # 更新统计
        _app_state["total_received"] += 1
        _app_state["last_received"] = datetime.now()

        if namespace not in _app_state["by_namespace"]:
            _app_state["by_namespace"][namespace] = {
                "count": 0,
                "last_received": None,
            }
        _app_state["by_namespace"][namespace]["count"] += 1
        _app_state["by_namespace"][namespace]["last_received"] = datetime.now().isoformat()

        # 验证平台类型
        if platform not in ("github", "gitee"):
            logger.warning(f"Unsupported platform: {platform}")
            raise HTTPException(status_code=400, detail=f"Unsupported platform: {platform}")

        # 获取租户配置
        tenant = tenant_manager.get_tenant(namespace)
        if not tenant:
            logger.warning(f"Tenant not found: {namespace}")
            raise HTTPException(status_code=404, detail=f"Tenant not found: {namespace}")

        # 验证平台是否匹配
        if tenant.git_platform != platform:
            logger.warning(
                f"Platform mismatch for {namespace}: expected {tenant.git_platform}, got {platform}"
            )
            raise HTTPException(
                status_code=400,
                detail=f"Platform mismatch: expected {tenant.git_platform}"
            )

        # 获取原始请求体
        payload = await request.body()

        # 验证签名
        if tenant.webhook_secret:
            verifier = WebhookVerifier(tenant.webhook_secret)

            # GitHub 和 Gitee 的签名头名称不同
            if platform == "github":
                signature_header = "X-Hub-Signature-256"
            else:  # gitee
                signature_header = "X-Gitee-Token"

            signature = request.headers.get(signature_header) or request.headers.get(signature_header.lower())

            # GitHub 使用 sha256= 前缀，Gitee 直接是 token
            if platform == "github":
                if not verifier.verify(payload, signature or ""):
                    logger.warning(f"Invalid webhook signature for {namespace}")
                    raise HTTPException(status_code=403, detail="Invalid signature")
            else:  # gitee 使用简单字符串比较
                expected_signature = tenant.webhook_secret
                if signature != expected_signature:
                    logger.warning(f"Invalid webhook signature for {namespace}")
                    raise HTTPException(status_code=403, detail="Invalid signature")
        else:
            logger.warning(f"No webhook secret configured for {namespace}, skipping signature verification")

        # 解析事件类型
        if platform == "github":
            event_type_header = "X-GitHub-Event"
            delivery_header = "X-GitHub-Delivery"
        else:  # gitee
            event_type_header = "X-Gitee-Event"
            delivery_header = "X-Gitee-Delivery"

        event_type = request.headers.get(event_type_header) or request.headers.get(event_type_header.lower(), "")
        delivery_id = request.headers.get(delivery_header) or request.headers.get(delivery_header.lower(), "")

        if not event_type:
            logger.warning(f"Missing {event_type_header} header")
            raise HTTPException(status_code=400, detail="Missing event type")

        # 解析 JSON
        try:
            payload_dict = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse webhook payload: {e}")
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

        # 创建事件对象
        event = WebhookEvent(
            event_type=event_type,
            delivery_id=delivery_id,
            payload=payload_dict,
            received_at=datetime.now(),
        )

        # 获取处理器并处理事件
        if _multi_tenant_handler is None:
            logger.warning("Handler not initialized, returning accepted")
            return JSONResponse(
                status_code=202,
                content={"status": "accepted", "message": "Handler not initialized"}
            )

        try:
            result = await _multi_tenant_handler.handle_event(namespace, event)
            return JSONResponse(content=result)
        except Exception as e:
            logger.error(f"Error handling webhook event for {namespace}: {e}", exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": str(e)}
            )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """全局异常处理"""
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Internal server error"}
        )

    return app


def get_multi_tenant_handler() -> Optional[MultiTenantWebhookHandler]:
    """获取多租户处理器实例"""
    return _multi_tenant_handler
