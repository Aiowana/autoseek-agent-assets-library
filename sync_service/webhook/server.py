"""
Webhook HTTP 服务器

使用 FastAPI 提供 HTTP 服务，接收 GitHub Webhook 请求。
"""

import logging
from datetime import datetime
from typing import Dict, Any

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import JSONResponse

from sync_service.config import Config
from sync_service.webhook.models import WebhookEvent
from sync_service.webhook.verifier import WebhookVerifier
from sync_service.webhook.handler import WebhookHandler

logger = logging.getLogger(__name__)

# 全局变量
_handler: WebhookHandler = None
_verifier: WebhookVerifier = None
_app_state: Dict[str, Any] = {}


def create_app(config: Config) -> FastAPI:
    """
    创建 FastAPI 应用

    Args:
        config: 应用配置

    Returns:
        FastAPI 应用实例
    """
    global _handler, _verifier

    app = FastAPI(
        title="Agent Asset Library Webhook Server",
        description="接收 GitHub Webhook 事件并触发资产同步",
        version="1.0.0",
    )

    # 初始化验证器
    if not config.webhook.secret:
        logger.warning("WEBHOOK_SECRET not set, signature verification disabled")
        _verifier = None
    else:
        _verifier = WebhookVerifier(config.webhook.secret)
        logger.info("Webhook signature verification enabled")

    # 初始化状态
    _app_state["start_time"] = datetime.now()
    _app_state["total_received"] = 0
    _app_state["last_received"] = None
    _app_state["last_sync_duration_ms"] = None

    @app.on_event("startup")
    async def startup():
        """应用启动时的初始化"""
        logger.info(f"Webhook server starting on {config.webhook.host}:{config.webhook.port}")
        logger.info(f"Target branch: {config.github.branch}")

    @app.on_event("shutdown")
    async def shutdown():
        """应用关闭时的清理"""
        logger.info("Webhook server shutting down")

    @app.get("/")
    async def root():
        """根路径"""
        return {
            "service": "Agent Asset Library Webhook Server",
            "status": "running",
            "version": "1.0.0",
        }

    @app.get("/health")
    async def health():
        """健康检查"""
        return {
            "status": "healthy",
            "uptime_seconds": (datetime.now() - _app_state["start_time"]).total_seconds(),
        }

    @app.get("/webhook/status")
    async def webhook_status():
        """Webhook 状态查询"""
        return {
            "configured": _verifier is not None,
            "secret_set": _verifier is not None,
            "events_supported": ["push", "ping"],
            "target_branch": config.github.branch,
            "stats": {
                "total_received": _app_state["total_received"],
                "last_received": _app_state["last_received"].isoformat() if _app_state["last_received"] else None,
                "last_sync_duration_ms": _app_state["last_sync_duration_ms"],
            },
        }

    @app.post("/webhook/github")
    async def github_webhook(request: Request):
        """
        GitHub Webhook 接收端点

        接收 GitHub 发送的 Webhook 事件，验证签名后触发相应的操作。
        """
        # 更新统计
        _app_state["total_received"] += 1
        _app_state["last_received"] = datetime.now()

        # 获取原始请求体
        payload = await request.body()

        # 验证签名
        if _verifier:
            signature = request.headers.get("X-Hub-Signature-256") or request.headers.get("x-hub-signature-256")
            if not _verifier.verify(payload, signature or ""):
                logger.warning("Invalid webhook signature")
                raise HTTPException(status_code=403, detail="Invalid signature")

        # 解析事件类型
        event_type = request.headers.get("X-GitHub-Event") or request.headers.get("x-github-event", "")
        delivery_id = request.headers.get("X-GitHub-Delivery") or request.headers.get("x-github-delivery", "")

        if not event_type:
            logger.warning("Missing X-GitHub-Event header")
            raise HTTPException(status_code=400, detail="Missing event type")

        # 解析 JSON
        try:
            import json
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
        if _handler is None:
            logger.warning("Handler not initialized, returning accepted")
            return JSONResponse(
                status_code=202,
                content={"status": "accepted", "message": "Handler not initialized"}
            )

        try:
            result = await _handler.handle_event(event)
            return JSONResponse(content=result)
        except Exception as e:
            logger.error(f"Error handling webhook event: {e}", exc_info=True)
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


def set_handler(handler: WebhookHandler):
    """设置 Webhook 处理器（需要在启动应用后调用）"""
    global _handler
    _handler = handler
    logger.info("Webhook handler initialized")


def get_app() -> FastAPI:
    """获取当前 FastAPI 应用实例"""
    # 这个函数主要用于在 uvicorn 启动时导入应用
    import sys
    if "_app" in sys.modules:
        return sys.modules["_app"]
    raise RuntimeError("Application not initialized. Use create_app() first.")
