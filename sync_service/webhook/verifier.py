"""
Webhook 签名验证器

验证 GitHub Webhook 请求的 HMAC-SHA256 签名。
"""

import hashlib
import hmac
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class WebhookVerifier:
    """
    GitHub Webhook 签名验证器

    使用 HMAC-SHA256 算法验证 Webhook 请求的签名，
    防止伪造请求和时序攻击。
    """

    def __init__(self, secret: str):
        """
        初始化验证器

        Args:
            secret: Webhook 密钥，从 GitHub Webhook 配置中获取
        """
        if not secret:
            raise ValueError("Webhook secret is required for signature verification")
        self.secret = secret

    def verify(self, payload: bytes, signature: str) -> bool:
        """
        验证 Webhook 签名

        Args:
            payload: 原始请求体（bytes）
            signature: X-Hub-Signature-256 请求头的值，格式为 "sha256=<hex_string>"

        Returns:
            bool: 签名是否有效

        Raises:
            ValueError: 如果签名格式无效
        """
        if not signature:
            logger.warning("Webhook signature is missing")
            return False

        # 解析签名
        if not signature.startswith("sha256="):
            logger.warning(f"Invalid signature format: {signature[:20]}...")
            return False

        received_signature = signature[7:]  # 移除 "sha256=" 前缀

        # 计算期望签名
        expected_signature = self._compute_signature(payload)

        # 使用常量时间比较，防止时序攻击
        is_valid = hmac.compare_digest(expected_signature, received_signature)

        if not is_valid:
            logger.warning("Webhook signature verification failed")

        return is_valid

    def _compute_signature(self, payload: bytes) -> str:
        """
        计算负载的 HMAC-SHA256 签名

        Args:
            payload: 原始请求体

        Returns:
            str: 十六进制签名字符串
        """
        mac = hmac.new(
            self.secret.encode("utf-8"),
            payload,
            hashlib.sha256
        )
        return mac.hexdigest()

    def verify_request(self, payload: bytes, headers: dict) -> bool:
        """
        从请求头中验证签名（便捷方法）

        Args:
            payload: 原始请求体
            headers: 请求头字典

        Returns:
            bool: 签名是否有效
        """
        # GitHub 使用 X-Hub-Signature-256 (推荐) 和 X-Hub-Signature (旧版)
        signature = (
            headers.get("X-Hub-Signature-256") or
            headers.get("x-hub-signature-256") or
            headers.get("X-Hub-Signature") or
            headers.get("x-hub-signature")
        )

        return self.verify(payload, signature)


# 工厂函数
def create_verifier(secret: str) -> WebhookVerifier:
    """创建 Webhook 验证器"""
    return WebhookVerifier(secret)
