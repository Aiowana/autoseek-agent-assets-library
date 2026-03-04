"""
Webhook 模块 - 接收和处理 GitHub Webhook 事件

本模块提供 FastAPI 服务器，用于接收 GitHub 发送的 Webhook 事件，
验证签名，并触发相应的同步操作。
"""

from sync_service.webhook.server import create_app

__all__ = ["create_app"]
