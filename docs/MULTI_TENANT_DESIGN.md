# Agent 资产库同步服务 - 多租户系统设计文档

## 文档信息

| 项目 | 说明 |
|------|------|
| **文档版本** | v1.1.0 |
| **最后更新** | 2025-01-15 |
| **维护者** | AutoSeek Team |
| **状态** | 设计阶段 |

---

## 目录

1. [概述](#1-概述)
2. [架构设计](#2-架构设计)
3. [数据模型](#3-数据模型)
4. [核心功能](#4-核心功能)
5. [API 设计](#5-api-设计)
6. [安全设计](#6-安全设计)
7. [资源管理](#7-资源管理)
8. [部署架构](#8-部署架构)
9. [迁移方案](#9-迁移方案)

---

## 1. 概述

### 1.1 背景

当前系统是**单租户**版本，只能管理一个 GitHub 仓库的资产。为了支持多个用户/项目各自管理独立的资产库，需要升级为**多租户**系统。

### 1.2 目标

- **多租户隔离**：每个租户拥有独立的 Git 仓库和 Redis 命名空间
- **水平扩展**：支持从 10 个租户扩展到 10,000 个租户
- **向后兼容**：保持与现有单租户系统的兼容性
- **自动化**：支持新租户的自动化接入

### 1.3 核心概念

#### 命名空间 (Namespace)

每个租户拥有一个唯一的命名空间标识符：

```
proj_{project_id}    # 项目级租户
user_{user_id}       # 用户级租户
org_{org_id}         # 组织级租户
```

#### 隔离机制

| 层级 | 隔离方式 | 示例 |
|------|----------|------|
| **Redis** | Key 前缀 | `asset:{ns}:metadata:*` |
| **Git** | 独立仓库 | 每个租户有自己的仓库 |
| **配置** | 租户级配置 | 独立的 Token 和 Webhook Secret |

---

## 2. 架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              用户层                                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐       │
│  │  项目 A     │  │  项目 B     │  │  用户 X     │  │  用户 Y     │       │
│  │  (proj_a)   │  │  (proj_b)   │  │  (user_x)   │  │  (user_y)   │       │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘       │
└─────────┼───────────────┼───────────────┼───────────────┼───────────────────┘
          │               │               │               │
          └───────────────┴───────────────┴───────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         多租户同步服务                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        Tenant Manager                               │   │
│  │  • 租户注册表 (Registry)                                          │   │
│  │  • 配置加载 (YAML/DB)                                             │   │
│  │  • 租户生命周期管理                                               │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Sync Engine (Per Tenant)                        │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                 │   │
│  │  │GitHub Manager│  │Redis Client │  │Lock Manager │                 │   │
│  │  │(多仓库支持)  │  │(命名空间隔离)│  │(按租户锁)   │                 │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      Webhook Router                                │   │
│  │  POST /webhook/{platform}/{namespace}                             │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          外部服务                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    GitHub / Gitee                                    │   │
│  │  • 多个独立仓库                                                     │   │
│  │  • 每个 Webhook → /webhook/github/{ns}                            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                       Redis / Tendis                                  │   │
│  │  asset:{ns}:metadata:{id}                                          │   │
│  │  asset:{ns}:index                                                 │   │
│  │  asset:{ns}:sync:state                                            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 模块架构

```
sync_service/
├── tenant.py                    # 租户管理 (新增)
│   ├── TenantConfig             # 租户配置
│   ├── TenantRegistry           # 租户注册表
│   └── TenantManager            # 租户管理器
│
├── redis_client.py              # 修改：支持命名空间前缀
├── github_manager.py            # 修改：支持多仓库
├── sync_service.py              # 修改：支持按租户同步
│
└── webhook/                     # 修改：动态路由
    ├── server.py                # 支持 /webhook/{platform}/{ns}
    ├── handler.py               # 按租户处理
    └── verifier.py              # 按租户验证签名
```

### 2.3 配置管理

#### 租户配置方式（渐进式）

| 阶段 | 配置方式 | 说明 |
|------|----------|------|
| **v1.0** | YAML 文件 | `tenants.yaml`，适合小规模 |
| **v1.5** | 环境变量 | 每个租户独立配置 |
| **v2.0** | PostgreSQL | 完整多租户 SaaS |

#### tenants.yaml 示例

```yaml
tenants:
  - namespace: "proj_alpha"
    name: "Alpha 项目"
    git_platform: "github"
    git_token: "${GITHUB_TOKEN_ALPHA}"
    git_repo: "alpha-team/agent-assets"
    git_branch: "main"
    webhook_secret: "${WEBHOOK_SECRET_ALPHA}"
    enabled: true

  - namespace: "proj_beta"
    name: "Beta 项目"
    git_platform: "github"
    git_token: "${GITHUB_TOKEN_BETA}"
    git_repo: "beta-company/agent-assets"
    git_branch: "main"
    webhook_secret: "${WEBHOOK_SECRET_BETA}"
    enabled: true

  - namespace: "user_alice"
    name: "Alice 的个人资产库"
    git_platform: "github"
    git_token: "${GITHUB_TOKEN_ALICE}"
    git_repo: "alice/agent-assets"
    git_branch: "main"
    webhook_secret: "${WEBHOOK_SECRET_ALICE}"
    enabled: true
```

---

## 3. 数据模型

### 3.1 Redis 数据结构（带命名空间）

```
# 资产元数据
Key:    asset:{namespace}:metadata:{asset_id}
Type:   Hash
Fields: id, version, category, name, description, ...

# 全局索引
Key:    asset:{namespace}:index
Type:   Hash
Fields: {asset_id}: {summary_json}

# 分类索引
Key:    asset:{namespace}:category:{category}
Type:   Set
Members: [asset_id, ...]

# 同步状态
Key:    asset:{namespace}:sync:state
Type:   Hash
Fields: last_sync_time, last_commit_sha, synced_count, sync_status

# 分布式锁
Key:    asset:{namespace}:sync:lock
Type:   String
Value:  "{pid}:{timestamp}"

# 实时日志
Key:    logs:stream:{namespace}
Type:   Stream
```

### 3.2 租户配置数据结构

```python
@dataclass
class TenantConfig:
    """租户配置"""
    namespace: str              # 命名空间 (唯一标识)
    name: str                   # 租户名称
    git_platform: str           # "github" | "gitee"
    git_token: str              # Git 访问令牌
    git_repo: str               # 仓库地址
    git_branch: str = "main"    # 分支名
    webhook_secret: str = ""    # Webhook 密钥
    enabled: bool = True        # 是否启用

    def get_redis_prefix(self) -> str:
        return f"asset:{self.namespace}"

    def get_webhook_path(self) -> str:
        return f"/webhook/{self.git_platform}/{self.namespace}"
```

### 3.3 PostgreSQL 数据模型（v2.0）

```sql
CREATE TABLE tenants (
    id UUID PRIMARY KEY,
    namespace VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    git_platform VARCHAR(20) NOT NULL,
    git_url VARCHAR(500) NOT NULL,
    access_token_encrypted TEXT NOT NULL,
    webhook_secret TEXT,
    last_commit_sha VARCHAR(64),
    is_private BOOLEAN DEFAULT FALSE,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_tenants_namespace ON tenants(namespace);
CREATE INDEX idx_tenants_enabled ON tenants(enabled);
```

---

## 4. 核心功能

### 4.1 租户管理

#### 注册租户

```python
# 方式 1：代码注册
tenant = TenantConfig(
    namespace="proj_alpha",
    name="Alpha 项目",
    git_platform="github",
    git_token="ghp_xxx",
    git_repo="owner/repo",
)
register_tenant(tenant)

# 方式 2：配置文件加载
load_tenants_from_config("tenants.yaml")
```

#### 租户生命周期

```
创建 → 配置 → 启用 → 同步 → 禁用 → 删除
  ↓      ↓      ↓      ↓       ↓       ↓
Provision  Sync  Active  Active  Inactive  Archived
```

### 4.2 按租户同步

```python
# 同步单个租户
sync_namespace("proj_alpha")

# 同步所有启用的租户
sync_all_tenants()

# 同步指定租户列表
sync_tenants(["proj_alpha", "proj_beta"])
```

### 4.3 资产联合检索 (Union View)

#### 需求背景

用户通常需要同时看到：
- **系统公共资产**：平台预置的工具、提示词
- **用户私有资产**：用户自己创建的资产

#### 合并规则

```
1. 读取 `asset:system_global:index` (系统预置)
2. 读取 `asset:user_{id}:index` (用户私有)
3. 进行 ID 合并：
   - 若发生 ID 冲突，用户资产覆盖系统资产
   - 系统资产作为"基础库"始终可用
```

#### 数据结构

```python
# 系统全局资产
asset:system_global:index
├── tool_search: {...}
├── tool_http_request: {...}
└── prompt_default: {...}

# 用户 Alice 的资产
asset:user_alice:index
├── tool_my_search: {...}
├── tool_search: {...}  # 覆盖系统版本
└── prompt_custom: {...}
```

#### API 实现

```python
def get_assets_union(namespace: str) -> Dict[str, Any]:
    """
    获取资产的联合视图

    Args:
        namespace: 用户命名空间 (如 "user_alice")

    Returns:
        合并后的资产字典
    """
    # 1. 读取系统全局资产
    system_assets = redis.hgetall("asset:system_global:index")

    # 2. 读取用户私有资产
    user_assets = redis.hgetall(f"asset:{namespace}:index")

    # 3. 合并（用户资产覆盖系统资产）
    merged = {**system_assets, **user_assets}

    # 4. 添加来源标记
    for asset_id, asset_json in merged.items():
        asset = json.loads(asset_json)
        if asset_id in user_assets:
            asset["_source"] = "user"
        else:
            asset["_source"] = "system"
        merged[asset_id] = json.dumps(asset)

    return merged
```

#### 系统资产命名空间

```
系统全局资产使用特殊命名空间：system_global

├── 开发者预先创建核心工具
├── 所有用户都可访问
└── 用户不能修改（只读）
```

### 4.4 动态 Webhook 路由

```
POST /webhook/github/proj_alpha   # 项目 A 的 Webhook
POST /webhook/github/proj_beta    # 项目 B 的 Webhook
POST /webhook/gitee/user_alice    # 用户 Alice 的 Webhook
```

**处理流程：**

```python
async def handle_webhook(platform: str, namespace: str, request: Request):
    # 1. 从租户注册表获取配置
    tenant = get_tenant(namespace)
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    # 2. 使用该租户的密钥验证签名
    verifier = WebhookVerifier(tenant.webhook_secret)
    if not verifier.verify(payload, signature):
        raise HTTPException(403, "Invalid signature")

    # 3. 创建该租户的同步服务
    sync_service = create_sync_service_for_tenant(tenant)

    # 4. 触发同步
    await trigger_sync(sync_service, tenant)
```

### 4.5 同步任务并发控制 (Worker Pool)

#### 问题

如果 1,000 个租户同时触发 Webhook，系统会瞬间产生 1,000 个同步任务，可能导致：
- CPU 爆表
- GitHub API 限流
- Redis 连接耗尽

#### 解决方案：任务队列 + Worker Pool

```
┌─────────────────────────────────────────────────────────────────┐
│                      Webhook 接收层                          │
│  POST /webhook/{platform}/{ns}                                  │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                     任务队列 (Redis Sorted Set)                 │
│  sync:tasks → [{ns, priority, created_at}, ...]                 │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Worker Pool (4-8 Workers)                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ Worker 1 │  │ Worker 2 │  │ Worker 3 │  │ Worker 4 │        │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘        │
│       │             │             │             │               │
│       └─────────────┴─────────────┴─────────────┘               │
│                     按优先级顺序处理同步任务                          │
└─────────────────────────────────────────────────────────────────┘
```

#### 配置项

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `WORKER_COUNT` | 4 | Worker 进程数量 |
| `TASK_QUEUE_MAX_SIZE` | 10000 | 任务队列最大长度 |
| `TASK_TIMEOUT` | 300 | 单个任务超时时间（秒） |

### 4.6 自动化创建仓库 (Tenant Provisioning)

#### 需求

当新用户注册时，自动：
1. 创建私有 Git 仓库
2. 初始化目录结构和模板
3. 配置 Webhook
4. 执行首次同步

#### 流程图

```
新租户注册
    │
    ▼
┌─────────────────────────────────────┐
│  1. 验证命名空间可用性              │
│     检查 namespace 是否已存在         │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  2. 创建 Git 仓库                   │
│     调用 GitHub/Gitee API            │
│     仓库名: agent-assets-{ns}        │
│     可见性: Private                  │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  3. 初始化仓库内容                   │
│     创建目录: tools/, prompts/       │
│     推送 README.md 和初始模板        │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  4. 配置 Webhook                    │
│     调用 Git API 创建 Webhook        │
│     URL: {service_url}/webhook/{platform}/{ns} │
│     Secret: 自动生成                 │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  5. 注册租户配置                     │
│     保存到 tenants.yaml / DB        │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  6. 首次同步                         │
│     执行 sync_namespace(ns)         │
└─────────────────────────────────────┘
```

#### 初始仓库模板

```
agent-assets-{ns}/
├── tools/                  # 工具目录
│   └── .gitkeep
├── prompts/                # 提示词目录
│   └── .gitkeep
├── skills/                 # 技能目录
│   └── .gitkeep
└── README.md               # 说明文档
```

### 4.7 租户注销与数据清理

#### 清理流程

```python
async def remove_tenant(namespace: str, cleanup_git: bool = False):
    """
    注销租户并清理数据

    Args:
        namespace: 租户命名空间
        cleanup_git: 是否删除 Git 仓库（通常保留）
    """
    # 1. 禁用租户
    tenant = get_tenant(namespace)
    if tenant:
        tenant.enabled = False
        logger.info(f"Tenant {namespace} disabled")

    # 2. 清理 Redis 数据
    await _cleanup_redis_namespace(namespace)

    # 3. 可选：删除 Git 仓库
    if cleanup_git:
        await _delete_git_repo(tenant)

    # 4. 从注册表移除
    unregister_tenant(namespace)

async def _cleanup_redis_namespace(namespace: str):
    """清理租户的 Redis 数据"""
    prefix = f"asset:{namespace}:"
    cursor = 0
    deleted_count = 0

    while True:
        # 使用 SCAN 遍历所有匹配的 Key
        cursor, keys = redis.scan(cursor, match=f"{prefix}*", count=1000)

        if keys:
            # 批量删除
            redis.delete(*keys)
            deleted_count += len(keys)
            logger.info(f"Cleaned {len(keys)} keys for {namespace}")

        if cursor == 0:
            break

    logger.info(f"Total cleaned: {deleted_count} keys for {namespace}")
```

---

## 5. API 设计

### 5.1 CLI 命令

```bash
# 同步所有租户
python main.py sync --all

# 同步指定租户
python main.py sync --tenant proj_alpha

# 列出所有租户
python main.py tenants

# 查看租户详情
python main.py tenant --namespace proj_alpha

# 添加租户
python main.py tenant add --namespace proj_alpha --config config.yaml

# 删除租户
python main.py tenant remove --namespace proj_alpha
```

### 5.2 HTTP API

```
# 租户管理
GET    /api/tenants                    # 列出所有租户
GET    /api/tenants/{ns}               # 获取租户详情
POST   /api/tenants                    # 创建租户
PUT    /api/tenants/{ns}               # 更新租户配置
DELETE /api/tenants/{ns}               # 删除租户
POST   /api/tenants/{ns}/sync          # 触发同步
GET    /api/tenants/{ns}/status        # 获取同步状态

# 资产查询（带命名空间）
GET    /api/{ns}/assets                # 获取资产列表
GET    /api/{ns}/assets/{id}           # 获取资产详情

# Webhook（动态路由）
POST   /webhook/{platform}/{ns}        # 接收 Webhook

# 健康检查
GET    /health                         # 服务健康状态
GET    /health/tenants                 # 所有租户状态
```

---

## 6. 安全设计

### 6.1 命名空间隔离

| 安全措施 | 实现 |
|----------|------|
| **Redis 隔离** | Key 前缀 `asset:{ns}:*` |
| **Git Token 隔离** | 每个租户独立 Token |
| **Webhook Secret 隔离** | 每个租户独立密钥 |
| **分布式锁隔离** | `asset:{ns}:sync:lock` |

### 6.2 访问控制

```python
# 简单方案：基于命名空间的访问控制
def check_access(namespace: str, token: str) -> bool:
    """检查是否有权访问该命名空间"""
    tenant = get_tenant(namespace)
    if not tenant or not tenant.enabled:
        return False
    # TODO: 验证 token
    return True
```

### 6.3 Token 管理

| 方案 | 适合场景 | 实现 |
|------|----------|------|
| **环境变量** | 小规模 | 每个租户一个环境变量 |
| **加密存储** | 大规模 | PostgreSQL 加密存储 |
| **外部服务** | 企业级 | Vault/HSM 集成 |

### 6.4 资源配额管理 (Resource Quotas)

为了防止单个租户占用过多系统资源，需要实施配额限制：

#### 配额限制

| 配额项 | 默认值 | 说明 |
|--------|--------|------|
| **Max Assets per Tenant** | 200 | 单个租户最大资产数 |
| **Max Manifest Size** | 512 KB | 单个 manifest 文件大小 |
| **Max Total Storage** | 100 MB | 单个租户 Redis 存储上限 |
| **Webhook Rate Limit** | 60 req/min | 单 IP 每分钟 Webhook 请求数 |
| **Sync Frequency** | 1 req/5min | 单个租户同步频率限制 |

#### 实现

```python
class QuotaManager:
    """租户资源配额管理"""

    QUOTAS = {
        "max_assets": 200,
        "max_manifest_size": 512 * 1024,  # 512 KB
        "max_total_storage": 100 * 1024 * 1024,  # 100 MB
    }

    def check_quota(self, namespace: str) -> Dict[str, Any]:
        """检查租户配额使用情况"""
        usage = {}

        # 检查资产数量
        asset_count = self.redis.hlen(f"asset:{namespace}:index")
        usage["asset_count"] = asset_count
        usage["asset_quota"] = self.QUOTAS["max_assets"]
        usage["asset_usage_percent"] = asset_count / self.QUOTAS["max_assets"] * 100

        # 检查存储大小
        storage_bytes = self._get_namespace_storage_size(namespace)
        usage["storage_bytes"] = storage_bytes
        usage["storage_quota"] = self.QUOTAS["max_total_storage"]
        usage["storage_usage_percent"] = storage_bytes / self.QUOTAS["max_total_storage"] * 100

        return usage

    def check_asset_quota(self, namespace: str, manifest_size: int) -> bool:
        """检查是否可以添加新资产"""
        # 检查数量限制
        current_count = self.redis.hlen(f"asset:{namespace}:index")
        if current_count >= self.QUOTAS["max_assets"]:
            raise QuotaExceededError(
                f"Asset limit reached: {current_count}/{self.QUOTAS['max_assets']}"
            )

        # 检查大小限制
        if manifest_size > self.QUOTAS["max_manifest_size"]:
            raise QuotaExceededError(
                f"Manifest too large: {manifest_size} > {self.QUOTAS['max_manifest_size']}"
            )

        return True
```

---

## 7. 部署架构

### 7.1 单机部署（小规模）

```
┌─────────────────────────────────────┐
│         单个服务器                   │
│  ┌─────────────────────────────┐    │
│  │   Sync Service               │    │
│  │   • 管理多个租户              │    │
│  │   • 每个租户独立同步          │    │
│  └──────────┬──────────────────┘    │
└─────────────┼───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│         Redis (本地)                 │
│  asset:proj_a:*                     │
│  asset:proj_b:*                     │
│  asset:user_x:*                     │
└─────────────────────────────────────┘
```

### 7.2 高可用部署（大规模）

```
┌─────────────────────────────────────────────────────────────────┐
│                         负载均衡 (Nginx)                         │
└────────────────────────────┬────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│ Sync Service  │    │ Sync Service  │    │ Sync Service  │
│   Instance 1  │    │   Instance 2  │    │   Instance 3  │
└───────┬───────┘    └───────┬───────┘    └───────┬───────┘
        │                    │                    │
        └────────────────────┼────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Redis Cluster                                │
│  asset:{ns}:*  (按租户分布式存储)                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 8. 迁移方案

### 8.1 从单租户到多租户

#### 阶段 1：兼容性改造

```python
# 保持现有 API 可用
python main.py sync  # 同步默认租户

# 新增多租户 API
python main.py sync --tenant proj_alpha
```

#### 阶段 2：配置迁移

```yaml
# tenants.yaml
tenants:
  - namespace: "default"      # 现有配置迁移为 default 租户
    name: "默认租户"
    git_token: "${GITHUB_TOKEN}"
    git_repo: "${GITHUB_REPO}"
    # ... 其他配置
```

#### 阶段 3：Webhook 迁移

```
旧: POST /webhook/github
新: POST /webhook/github/{namespace}
```

**迁移期兼容：** 两个端点同时存在。

### 8.2 Redis Key 迁移

```python
# 旧 Key
asset:metadata:{id}
asset:index

# 新 Key
asset:default:metadata:{id}
asset:default:index

# 迁移脚本
def migrate_to_namespace(old_prefix="", new_namespace="default"):
    for key in redis.scan(f"{old_prefix}*"):
        new_key = key.replace(old_prefix, f"asset:{new_namespace}:")
        redis.rename(key, new_key)
```

---

## 9. 开发计划

### Phase 1: 核心多租户支持 (2-3 天)

- [ ] 创建 `tenant.py` 模块
- [ ] 实现租户配置管理
- [ ] 修改 RedisClient 支持命名空间
- [ ] 修改 GitHubManager 支持多仓库
- [ ] 更新 CLI 命令

### Phase 2: Webhook 动态路由 (1-2 天)

- [ ] 修改 Webhook 路由
- [ ] 实现按租户验证签名
- [ ] 更新 Webhook 文档

### Phase 3: 测试与文档 (1-2 天)

- [ ] 单元测试
- [ ] 集成测试
- [ ] 更新用户文档

### Phase 4: PostgreSQL 集成 (可选，3-5 天)

- [ ] 数据库模型
- [ ] Token 加密存储
- [ ] 管理 API

---

## 10. 附录

### A. 配置示例

#### tenants.yaml

```yaml
tenants:
  - namespace: "default"
    name: "默认租户"
    git_platform: "github"
    git_token: "${GITHUB_TOKEN}"
    git_repo: "Aiowana/autoseek-agent-assets-library"
    git_branch: "main"
    webhook_secret: "${GITHUB_WEBHOOK_SECRET}"
    enabled: true
```

### B. 命名空间命名规范

| 前缀 | 用途 | 示例 |
|------|------|------|
| `proj_` | 项目级 | `proj_alpha`, `proj_beta` |
| `user_` | 用户级 | `user_001`, `user_alice` |
| `org_` | 组织级 | `org_acme`, `org_startup` |
| `env_` | 环境级 | `env_prod`, `env_staging` |

### C. 相关文档

| 文档 | 说明 |
|------|------|
| [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) | 系统总体设计 |
| [WEBHOOK_DESIGN.md](WEBHOOK_DESIGN.md) | Webhook 设计 |
| [REDIS_KEY_CONVENTION.md](REDIS_KEY_CONVENTION.md) | Redis 规范 |

---

*本文档由 AutoSeek Team 维护，如有疑问请联系维护者。*
