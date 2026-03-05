"""
多租户管理模块

提供租户配置、注册表和管理器功能，支持从 YAML 文件加载租户配置。
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()


# ============================================================================
# 租户配置
# ============================================================================

@dataclass
class TenantConfig:
    """
    租户配置

    每个租户拥有独立的 Git 仓库和 Redis 命名空间。
    """

    namespace: str              # 命名空间 (唯一标识)
    name: str                   # 租户名称
    git_platform: str           # "github" | "gitee"
    git_token: str              # Git 访问令牌
    git_repo: str               # 仓库地址 (owner/repo)
    git_branch: str = "main"    # 分支名
    webhook_secret: str = ""    # Webhook 密钥
    enabled: bool = True        # 是否启用
    metadata: Dict[str, Any] = field(default_factory=dict)  # 额外的元数据

    def get_redis_prefix(self) -> str:
        """获取 Redis key 前缀"""
        return f"asset:{self.namespace}"

    def get_webhook_path(self) -> str:
        """获取 Webhook 路径"""
        return f"/webhook/{self.git_platform}/{self.namespace}"

    @property
    def owner(self) -> str:
        """提取仓库所有者"""
        return self.git_repo.split("/")[0]

    @property
    def repo_name(self) -> str:
        """提取仓库名称"""
        return self.git_repo.split("/")[1]

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "namespace": self.namespace,
            "name": self.name,
            "git_platform": self.git_platform,
            "git_repo": self.git_repo,
            "git_branch": self.git_branch,
            "enabled": self.enabled,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TenantConfig":
        """
        从字典创建配置

        支持环境变量扩展，如 "${GITHUB_TOKEN}"
        """
        def _expand_env(value: str) -> str:
            """展开环境变量"""
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                env_var = value[2:-1]
                return os.getenv(env_var, value)
            return value

        return cls(
            namespace=data["namespace"],
            name=data["name"],
            git_platform=data.get("git_platform", "github"),
            git_token=_expand_env(data.get("git_token", "")),
            git_repo=data.get("git_repo", ""),
            git_branch=data.get("git_branch", "main"),
            webhook_secret=_expand_env(data.get("webhook_secret", "")),
            enabled=data.get("enabled", True),
            metadata=data.get("metadata", {}),
        )


# ============================================================================
# 租户注册表
# ============================================================================

class TenantRegistry:
    """
    租户注册表

    管理所有租户配置，支持按命名空间查找租户。
    """

    def __init__(self):
        """初始化注册表"""
        self._tenants: Dict[str, TenantConfig] = {}

    def register(self, tenant: TenantConfig) -> None:
        """
        注册租户

        Args:
            tenant: 租户配置
        """
        if tenant.namespace in self._tenants:
            logger.warning(f"Tenant {tenant.namespace} already registered, updating")

        self._tenants[tenant.namespace] = tenant
        logger.info(f"Registered tenant: {tenant.namespace} ({tenant.name})")

    def unregister(self, namespace: str) -> bool:
        """
        注销租户

        Args:
            namespace: 命名空间

        Returns:
            是否成功注销
        """
        if namespace in self._tenants:
            del self._tenants[namespace]
            logger.info(f"Unregistered tenant: {namespace}")
            return True
        return False

    def get(self, namespace: str) -> Optional[TenantConfig]:
        """
        获取租户配置

        Args:
            namespace: 命名空间

        Returns:
            租户配置，不存在则返回 None
        """
        return self._tenants.get(namespace)

    def get_all(self) -> List[TenantConfig]:
        """获取所有租户配置"""
        return list(self._tenants.values())

    def get_enabled(self) -> List[TenantConfig]:
        """获取所有启用的租户"""
        return [t for t in self._tenants.values() if t.enabled]

    def exists(self, namespace: str) -> bool:
        """检查租户是否存在"""
        return namespace in self._tenants

    def clear(self) -> None:
        """清空注册表"""
        self._tenants.clear()
        logger.info("Cleared tenant registry")

    def count(self) -> int:
        """获取租户数量"""
        return len(self._tenants)

    def list_namespaces(self) -> List[str]:
        """获取所有命名空间"""
        return list(self._tenants.keys())


# ============================================================================
# 租户管理器
# ============================================================================

class TenantManager:
    """
    租户管理器

    提供租户的完整生命周期管理，包括加载、注册、查询等操作。
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化租户管理器

        Args:
            config_path: 租户配置文件路径 (tenants.yaml)
        """
        self.registry = TenantRegistry()
        self.config_path = config_path

        if config_path:
            self.load_from_yaml(config_path)

    def load_from_yaml(self, path: str) -> int:
        """
        从 YAML 文件加载租户配置

        Args:
            path: 配置文件路径

        Returns:
            加载的租户数量
        """
        config_file = Path(path)
        if not config_file.exists():
            logger.warning(f"Tenant config file not found: {path}")
            return 0

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not data or "tenants" not in data:
                logger.warning(f"No tenants found in config file: {path}")
                return 0

            count = 0
            for tenant_data in data["tenants"]:
                try:
                    tenant = TenantConfig.from_dict(tenant_data)
                    self.registry.register(tenant)
                    count += 1
                except Exception as e:
                    logger.error(f"Failed to load tenant {tenant_data.get('namespace', 'unknown')}: {e}")

            logger.info(f"Loaded {count} tenants from {path}")
            return count

        except Exception as e:
            logger.error(f"Failed to load tenant config from {path}: {e}")
            return 0

    def add_tenant(self, tenant: TenantConfig) -> bool:
        """
        添加新租户

        Args:
            tenant: 租户配置

        Returns:
            是否添加成功
        """
        if self.registry.exists(tenant.namespace):
            logger.warning(f"Tenant {tenant.namespace} already exists")
            return False

        self.registry.register(tenant)
        return True

    def remove_tenant(self, namespace: str) -> bool:
        """
        移除租户

        Args:
            namespace: 命名空间

        Returns:
            是否移除成功
        """
        return self.registry.unregister(namespace)

    def get_tenant(self, namespace: str) -> Optional[TenantConfig]:
        """获取租户配置"""
        return self.registry.get(namespace)

    def list_tenants(self, enabled_only: bool = False) -> List[TenantConfig]:
        """
        列出所有租户

        Args:
            enabled_only: 是否只列出启用的租户

        Returns:
            租户配置列表
        """
        if enabled_only:
            return self.registry.get_enabled()
        return self.registry.get_all()

    def get_namespace_prefix(self, namespace: str) -> str:
        """
        获取租户的 Redis key 前缀

        Args:
            namespace: 命名空间

        Returns:
            Redis key 前缀
        """
        tenant = self.get_tenant(namespace)
        if not tenant:
            raise ValueError(f"Tenant not found: {namespace}")
        return tenant.get_redis_prefix()

    def validate_namespace(self, namespace: str) -> bool:
        """
        验证命名空间格式

        命名空间应遵循以下规则：
        - 只包含小写字母、数字、下划线
        - 以 proj_, user_, org_ 或 env_ 开头
        - 长度在 3-50 字符之间

        Args:
            namespace: 命名空间

        Returns:
            是否有效
        """
        if not namespace:
            return False

        # 检查长度
        if len(namespace) < 3 or len(namespace) > 50:
            return False

        # 检查前缀
        valid_prefixes = ("proj_", "user_", "org_", "env_", "system_")
        if not namespace.startswith(valid_prefixes):
            return False

        # 检查字符
        valid_chars = set("abcdefghijklmnopqrstuvwxyz0123456789_")
        if not set(namespace).issubset(valid_chars):
            return False

        return True

    def get_status(self) -> Dict[str, Any]:
        """
        获取租户管理器状态

        Returns:
            状态信息字典
        """
        all_tenants = self.registry.get_all()
        enabled_tenants = self.registry.get_enabled()

        return {
            "total_tenants": len(all_tenants),
            "enabled_tenants": len(enabled_tenants),
            "disabled_tenants": len(all_tenants) - len(enabled_tenants),
            "namespaces": self.registry.list_namespaces(),
        }


# ============================================================================
# 全局单例
# ============================================================================

_tenant_manager: Optional[TenantManager] = None


def get_tenant_manager() -> TenantManager:
    """
    获取全局租户管理器单例

    Returns:
        租户管理器实例
    """
    global _tenant_manager
    if _tenant_manager is None:
        _tenant_manager = TenantManager()
    return _tenant_manager


def init_tenant_manager(config_path: Optional[str] = None) -> TenantManager:
    """
    初始化全局租户管理器

    Args:
        config_path: 租户配置文件路径

    Returns:
        租户管理器实例
    """
    global _tenant_manager
    _tenant_manager = TenantManager(config_path)
    return _tenant_manager


def reset_tenant_manager() -> None:
    """重置全局租户管理器（主要用于测试）"""
    global _tenant_manager
    _tenant_manager = None
