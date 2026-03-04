# Agent 资产库同步服务 - 系统设计文档

## 文档信息

| 项目 | 说明 |
|------|------|
| **文档版本** | v2.1.0 |
| **最后更新** | 2025-01-15 |
| **维护者** | AutoSeek Team |
| **状态** | 活跃开发 |

---

## 目录

1. [系统概述](#1-系统概述)
2. [架构设计](#2-架构设计)
3. [数据模型与协议](#3-数据模型与协议)
4. [核心功能设计](#4-核心功能设计)
5. [API 设计](#5-api-设计)
6. [安全设计](#6-安全设计)
7. [部署架构](#7-部署架构)
8. [可观测性](#8-可观测性)
9. [扩展性设计](#9-扩展性设计)
10. [高可用与容错设计](#10-高可用与容错设计)
11. [开发路线图](#11-开发路线图)

---

## 1. 系统概述

### 1.1 背景

在构建 AI Agent 操作系统的过程中，需要管理大量的可复用组件（工具、提示词、技能）。这些组件需要：

- **版本化管理**：追踪资产变更历史
- **快速检索**：前端需要秒级获取资产列表
- **双向同步**：开发者通过 Git 管理资产，用户通过 UI 使用资产
- **实时更新**：代码变更后快速反映到系统

### 1.2 系统定位

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Agent 操作系统                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
│  │  Chat UI    │  │  Agent      │  │  Workflow   │  │  Marketplace│ │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘ │
│         │                │                │                │         │
│         └────────────────┼────────────────┼────────────────┘         │
│                          ▼                │                          │
│              ┌───────────────────────────────┐                      │
│              │      资产库同步服务 (本文档)      │                      │
│              │   • 元数据存储                  │                      │
│              │   • 快速检索                    │                      │
│              │   • 版本管理                    │                      │
│              └───────────────┬───────────────┘                      │
│                              │                                       │
│                              ▼                                       │
│              ┌───────────────────────────────┐                      │
│              │     GitHub 仓库 (资产库)       │                      │
│              │   tools/  prompts/  skills/   │                      │
│              └───────────────────────────────┘                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.3 核心价值

| 价值维度 | 说明 |
|----------|------|
| **Single Source of Truth** | GitHub 仓库是资产的唯一真实来源 |
| **GitOps 实践** | 开发者通过 PR/CI 管理资产，无需额外后台 |
| **高性能检索** | Redis 提供毫秒级查询响应 |
| **双向同步** | 支持从 UI 创建/更新资产，自动写回 GitHub |
| **开放协议** | 标准 manifest.yaml 格式，易于扩展 |

### 1.4 系统边界

```
                ┌─────────────────────────────────────┐
                │           系统边界                   │
                │  ┌───────────────────────────────┐  │
                │  │  同步服务 (本系统)             │  │
                │  │  • CLI 工具                    │  │
                │  │  • Webhook 服务器              │  │
                │  │  • HTTP API (未来)             │  │
                │  └───────────────────────────────┘  │
                │                                     │
  ┌─────────────┼─────────────┐       ┌──────────────┼─────────────┐
  │   GitHub    │             │       │    Redis     │             │
  │  Repository │◄────────────┼───────►│   / Tendis   │             │
  │             │             │       │              │             │
  └─────────────┼─────────────┘       └──────────────┼─────────────┘
                │                                     │
                │                                     │
  ┌─────────────┼─────────────┐       ┌──────────────┼─────────────┐
  │   开发者    │             │       │    前端 UI    │             │
  │  (Git Push) │             │       │   (查询资产)  │             │
  └─────────────┴─────────────┘       └──────────────┴─────────────┘
```

---

## 2. 架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              GitHub Repository                               │
│                          (Single Source of Truth)                            │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐          │
│  │   tools/         │  │   prompts/       │  │   skills/        │          │
│  │  ┌────────────┐  │  │  ┌────────────┐  │  │  ┌────────────┐  │          │
│  │  │tool_a/     │  │  │  │prompt_x/   │  │  │  │skill_m/    │  │          │
│  │  │  manifest  │  │  │  │  manifest  │  │  │  │  manifest  │  │          │
│  │  │  handler.py│  │  │  │  template  │  │  │  │  handler.py│  │          │
│  │  └────────────┘  │  │  └────────────┘  │  │  └────────────┘  │          │
│  │  ┌────────────┐  │  │  ┌────────────┐  │  │  ┌────────────┐  │          │
│  │  │tool_b/     │  │  │  │prompt_y/   │  │  │  │skill_n/    │  │          │
│  │  │  manifest  │  │  │  │  manifest  │  │  │  │  manifest  │  │          │
│  │  └────────────┘  │  │  └────────────┘  │  │  └────────────┘  │          │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                ┌───────────────────┼───────────────────┐
                │                   │                   │
                │                   │                   │
                ▼                   ▼                   ▼
    ┌───────────────┐   ┌───────────────┐   ┌───────────────┐
    │  Polling      │   │  Webhook      │   │  CLI          │
    │  Mode         │   │  Mode         │   │  Mode         │
    │  (轮询触发)    │   │  (事件触发)    │   │  (手动触发)   │
    └───────┬───────┘   └───────┬───────┘   └───────┬───────┘
            │                   │                   │
            └───────────────────┼───────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Sync Service Core                                │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         AssetSyncService                            │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────────┐  │   │
│  │  │   Config    │  │   Logger    │  │   Metrics   │  │   Errors  │  │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └───────────┘  │   │
│  │                                                                       │   │
│  │  ┌───────────────────────────────────────────────────────────────┐  │   │
│  │  │                      Sync Logic                              │  │   │
│  │  │  • sync_from_github()     全量同步                           │  │   │
│  │  │  • incremental_sync()     增量同步 (SHA 检测)                 │  │   │
│  │  │  • create_asset()         创建资产 (UI → GitHub → Redis)     │  │   │
│  │  │  • update_asset()         更新资产                            │  │   │
│  │  │  • delete_asset()         删除资产                            │  │   │
│  │  └───────────────────────────────────────────────────────────────┘  │   │
│  │                                                                       │   │
│  │  ┌───────────────┐  ┌───────────────┐  ┌───────────────────────┐    │   │
│  │  │ GitHubManager │  │ RedisClient   │  │  ManifestValidator    │    │   │
│  │  │               │  │               │  │                       │    │   │
│  │  │ • scan_repo   │  │ • atomic_ops  │  │ • JSON Schema         │    │   │
│  │  │ • parse_yaml  │  │ • index_maint │  │ • Pydantic Models     │    │   │
│  │  │ • api_wrapper │  │ • state_track │  │ • Error Reporting     │    │   │
│  │  └───────────────┘  └───────────────┘  └───────────────────────┘    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Redis / Tendis                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                           Data Layer                                │   │
│  │                                                                      │   │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐     │   │
│  │  │ asset:metadata  │  │  asset:index    │  │ asset:category  │     │   │
│  │  │     {id}        │  │   (全局索引)     │  │   {category}    │     │   │
│  │  │     Hash        │  │     Hash        │  │      Set        │     │   │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────┘     │   │
│  │                                                                      │   │
│  │  ┌─────────────────┐  ┌─────────────────┐                          │   │
│  │  │ asset:sync:state│  │ asset:sync:changed│                         │   │
│  │  │     Hash        │  │      List        │                          │   │
│  │  └─────────────────┘  └─────────────────┘                          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              消费者层                                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐       │
│  │ Chat UI     │  │ Agent SDK   │  │ Workflow    │  │ HTTP API    │       │
│  │ (前端展示)   │  │ (调用工具)   │  │ (编排)      │  │ (第三方集成) │       │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘       │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 模块架构

```
sync_service/
├── __init__.py                    # 模块导出
├── config.py                      # 配置管理
├── models.py                      # 数据模型
├── schema.py                      # JSON Schema 定义
├── logger.py                      # 日志配置
├── logging_config.py              # 彩色日志格式化器
│
├── redis_client.py                # Redis 操作封装
│   ├── 连接管理
│   ├── Pipeline 事务
│   ├── 索引维护
│   └── 状态追踪
│
├── github_manager.py              # GitHub API 封装
│   ├── 仓库扫描
│   ├── 文件解析
│   ├── 变更检测
│   └── 文件读写
│
├── sync_service.py                # 同步服务核心
│   ├── GitHub → Redis 同步
│   ├── Redis → GitHub 写回
│   ├── 增量同步 (SHA 检测)
│   └── 差异计算
│
└── webhook/                       # Webhook 模块 (规划中)
    ├── server.py                  # FastAPI 服务器
    ├── handler.py                 # 事件处理器
    ├── verifier.py                # 签名验证
    └── models.py                  # Webhook 数据模型
```

### 2.3 技术选型

| 组件 | 技术选型 | 状态 | 理由 |
|------|----------|------|------|
| **语言** | Python 3.10+ | ✅ 已实现 | 生态丰富，AI/数据处理库成熟 |
| **GitHub API** | PyGithub | ✅ 已实现 | 官方推荐，API 覆盖完整 |
| **元数据存储** | Redis / Tendis | ✅ 已实现 | 高性能 KV 存储，支持复杂数据结构 |
| **配置管理** | Pydantic Settings | ✅ 已实现 | 类型安全，支持环境变量 |
| **数据校验** | jsonschema + Pydantic | ✅ 已实现 | 标准 JSON Schema 校验 |
| **日志** | ColorFormatter + RedisStreamHandler | ✅ 已实现 | 彩色输出 + 实时推送 |
| **HTTP 服务** | FastAPI | 🚧 规划中 | 异步支持，自动 API 文档 |
| **监控** | Prometheus | 📋 未来规划 | 云原生监控标准 |

### 2.4 数据流转

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              数据流转路径                                    │
└─────────────────────────────────────────────────────────────────────────────┘

1. 读取同步路径 (GitHub → Redis)

   GitHub File (manifest.yaml)
        │
        │ PyGithub: get_contents()
        ▼
   GitHubFile { path, content, sha }
        │
        │ yaml.safe_load()
        ▼
   Dict (原始数据)
        │
        │ ManifestValidator.validate_and_parse()
        ▼
   ManifestData (Pydantic Model)
        │
        │ 封装为 Asset
        ▼
   Asset { manifest, github_path, github_sha }
        │
        │ asset.to_stored_asset()
        ▼
   StoredAsset (JSON 序列化)
        │
        │ RedisClient.save_asset_atomic()
        ▼
   Redis Hash: asset:metadata:{id}


2. 写回同步路径 (UI → GitHub → Redis)

   UI 提交表单
        │
        │ HTTP POST /api/assets
        ▼
   Backend 接收请求
        │
        │ ManifestValidator.validate_and_parse()
        ▼
   ManifestData
        │
        │ GitHubManager.save_to_github()
        ▼
   GitHub API: create/update file
        │
        │ 返回新的 content SHA
        ▼
   GitHubManager.get_asset_by_id()
        │
        │ 重新解析 GitHub 文件
        ▼
   Asset (from GitHub)
        │
        │ RedisClient.save_asset_atomic()
        ▼
   Redis Hash: asset:metadata:{id}
```

---

## 3. 数据模型与协议

### 3.1 Manifest 协议

所有资产必须包含 `manifest.yaml` 文件：

#### 3.1.1 已支持的字段 (v1.0)

```yaml
# ========== 基础元数据 ==========
id: "unique_asset_id"              # 必需，正则: ^[a-zA-Z0-9_-]+$
version: "1.0.0"                    # 必需，语义化版本
category: "tool"                    # 必需，枚举: tool | prompt | skill
name: "Display Name"                # 必需，前端展示名称
description: "Asset description"    # 必需，功能描述
author: "Author Name"               # 可选，作者信息

# ========== 前端表单配置 ==========
config_schema:
  - name: "param_key"               # 必需，变量名
    label: "参数名"                  # 必需，前端显示标签
    type: "string"                  # 必需，枚举: string|number|select|secret|boolean
    required: true                  # 可选，默认 false
    default: null                   # 可选，默认值
    placeholder: "提示文字"          # 可选
    options:                        # select 类型专用
      - { label: "选项A", value: "A" }

# ========== LLM Function Calling 定义 ==========
agent_specs:
  function_name: "call_name"        # 必需，函数名
  description: "告诉 AI 何时调用此工具"  # 必需
  parameters:                       # 必需，JSON Schema 格式
    type: "object"
    properties:
      input_param:
        type: "string"
        description: "参数说明"
    required: ["input_param"]

# ========== 运行时配置 ==========
runtime:
  language: "python"                # 必需，当前仅支持 python
  entry: "main.py"                  # 必需，入口文件
  handler: "main_handler"           # 必需，入口函数名
  dependencies:                     # 可选，依赖列表
    - "requests>=2.31.0"

# ========== 权限配置 ==========
permissions:
  network_access: true              # 可选，是否允许网络访问
  filesystem_read: false            # 可选，是否允许读取文件
```

#### 3.1.2 规划中的字段 (v2.0)

以下字段在当前 schema 中**尚未实现**，计划在后续版本添加：

```yaml
# [PLANNED] config_schema 扩展
config_schema:
  - name: "param_key"
    validation:                     # 规划中：字段验证规则
      pattern: "^[a-z]+$"
      min: 1
      max: 100

# [PLANNED] runtime 扩展
runtime:
  environment:                      # 规划中：环境变量注入
    API_KEY: "${env.API_KEY}"

# [PLANNED] permissions 扩展
permissions:
  filesystem_write: false           # 规划中：写入权限
  allow_commands: []                # 规划中：命令白名单

# [PLANNED] 扩展元数据
metadata:                          # 规划中：扩展信息
  tags: ["search", "api"]
  icon: "search.svg"
  deprecated: false
```

### 3.2 Redis 数据结构

#### 3.2.1 资产元数据

```
Key:    asset:metadata:{id}
Type:   Hash
TTL:    永久
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 资产 ID |
| `version` | string | 版本号 |
| `category` | string | 类别 |
| `name` | string | 名称 |
| `description` | string | 描述 |
| `author` | string | 作者 |
| `config_schema` | json | 配置 Schema (JSON 字符串) |
| `agent_specs` | json | LLM 规范 (JSON 字符串) |
| `runtime` | json | 运行时配置 (JSON 字符串) |
| `permissions` | json | 权限配置 (JSON 字符串) |
| `github_path` | string | GitHub 文件路径 |
| `github_sha` | string | GitHub 文件 SHA |
| `created_at` | timestamp | 创建时间 |
| `updated_at` | timestamp | 更新时间 |

#### 3.2.2 全局轻量索引

```
Key:    asset:index
Type:   Hash
TTL:    永久
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `{id}` | json | 资产摘要 JSON: `{"id":"...","name":"...","category":"...","version":"...","description":"..."}` |

**用途**：前端列表页快速获取所有资产摘要，减少 90% 数据传输。

#### 3.2.3 分类索引

```
Key:    asset:category:{category}
Type:   Set
TTL:    永久
```

存储指定类别下的所有资产 ID。

#### 3.2.4 同步状态

```
Key:    asset:sync:state
Type:   Hash
TTL:    永久
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `last_sync_time` | timestamp | 上次同步时间 |
| `last_commit_sha` | string | 上次同步的 Commit SHA |
| `synced_count` | int | 已同步资产数 |
| `sync_status` | string | 状态: idle \| syncing \| failed |

#### 3.2.5 变更记录

```
Key:    asset:sync:changed
Type:   List
TTL:    永久
```

记录最近变更的资产 ID，保留最近 1000 条。

### 3.3 代码数据模型

```python
# 数据流转链路
GitHubFile
  ├─ path: str
  ├─ content: str
  ├─ sha: str
  └─ download_url: str
       │
       ▼
ManifestData (Pydantic)
  ├─ id: str
  ├─ version: str
  ├─ category: Literal["tool", "prompt", "skill"]
  ├─ name: str
  ├─ description: str
  ├─ author: Optional[str]
  ├─ config_schema: List[ConfigSchemaItem]
  ├─ agent_specs: Optional[AgentSpecs]
  ├─ runtime: Optional[RuntimeConfig]
  └─ permissions: Optional[Permissions]
       │
       ▼
Asset
  ├─ manifest: ManifestData
  ├─ github_path: str
  ├─ github_sha: str
  └─ github_url: str
       │
       ▼
StoredAsset
  ├─ id: str
  ├─ version: str
  ├─ config_schema: str  # JSON 字符串
  ├─ agent_specs: str    # JSON 字符串
  ├─ runtime: str        # JSON 字符串
  └─ permissions: str    # JSON 字符串
```

---

## 4. 核心功能设计

### 4.1 同步机制

#### 4.1.1 全量同步

```
┌─────────────────────────────────────────────────────────────┐
│ 1. 获取最新 Commit SHA                                       │
│    github.get_latest_commit_sha()                            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. 对比 last_commit_sha                                      │
│    if current_sha == last_sha: 跳过同步                      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. 扫描 GitHub 仓库                                          │
│    github.fetch_and_parse_all()                              │
│    ├─ 递归遍历目录                                           │
│    ├─ 查找 manifest.yaml                                     │
│    └─ 返回 List[Asset]                                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. 差异检测                                                   │
│    对比 GitHub 资产 vs Redis 资产:                           │
│    ├─ 新资产: CREATE                                         │
│    ├─ SHA 变更: UPDATE                                       │
│    ├─ Redis 有但 GitHub 无: DELETE                          │
│    └─ SHA 相同: SKIP                                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. 写入 Redis (原子操作)                                     │
│    redis.save_asset_atomic()                                 │
│    ├─ Pipeline: HSET metadata                               │
│    ├─ Pipeline: SADD category                                │
│    ├─ Pipeline: HSET index                                   │
│    └─ Pipeline: EXEC                                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. 更新同步状态                                               │
│    ├─ last_commit_sha = current_sha                          │
│    ├─ last_sync_time = now()                                 │
│    └─ sync_status = "idle"                                   │
└─────────────────────────────────────────────────────────────┘
```

#### 4.1.2 增量同步 (Commit SHA 检测)

```python
def incremental_sync():
    current_sha = github.get_latest_commit_sha()
    last_sha = redis.get_last_commit_sha()

    if last_sha is None:
        # 首次同步，执行全量
        return sync_from_github()

    if current_sha == last_sha:
        # 无变化，跳过
        return SyncStats(skipped=True)

    # 有变化，执行同步
    return sync_from_github()
```

### 4.2 反向写入 (UI → GitHub)

```python
def create_asset(manifest_data, author):
    # 1. 校验数据
    manifest = validator.validate_and_parse(manifest_data)

    # 2. 写入 GitHub
    success, result = github.save_to_github(
        asset_id=manifest.id,
        manifest_data=manifest.dict(),
        commit_message=f"Create asset: {manifest.id}\n\nAuthor: {author}"
    )

    # 3. 同步回 Redis
    asset = github.get_asset_by_id(manifest.id)
    redis.save_asset_atomic(asset.to_stored_asset())

    return success, result
```

**注意**：当前实现未包含冲突检测。当多个用户同时修改同一资产时，可能出现覆盖问题。解决方案见 [10.3 冲突处理](#103-冲突处理-乐观锁)。

### 4.3 Webhook 模式 (规划中)

详见 `docs/WEBHOOK_DESIGN.md`

---

## 5. API 设计

### 5.1 CLI 命令

| 命令 | 说明 |
|------|------|
| `python main.py sync` | 一次性全量同步 |
| `python main.py sync --incremental` | 增量同步 |
| `python main.py sync --continuous` | 持续轮询同步 |
| `python main.py health` | 健康检查 |
| `python main.py list` | 列出所有资产 |
| `python main.py list --category tool` | 按分类筛选 |
| `python main.py get <asset_id>` | 查看资产详情 |
| `python main.py index` | 获取全局索引 |
| `python main.py index --json` | 输出 JSON 格式 |
| `python main.py serve` | 启动 Webhook 服务器 (规划) |

### 5.2 HTTP API (规划)

```
GET    /api/assets                 # 获取资产列表 (轻量索引)
GET    /api/assets/{id}            # 获取资产详情
GET    /api/assets?category=tool   # 按分类筛选
POST   /api/assets                 # 创建资产
PUT    /api/assets/{id}            # 更新资产
DELETE /api/assets/{id}            # 删除资产
GET    /api/health                 # 健康检查
GET    /api/sync/trigger           # 手动触发同步
GET    /api/sync/status            # 同步状态
POST   /webhook/github             # Webhook 端点
```

---

## 6. 安全设计

### 6.1 认证与授权

| 场景 | 方案 |
|------|------|
| GitHub API | Personal Access Token (PAT) |
| Webhook | HMAC-SHA256 签名验证 |
| HTTP API | JWT Token (规划) |

### 6.2 签名验证

```python
def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)
```

### 6.3 权限隔离

```python
# Redis Key 隔离
KEY_PREFIX = "asset:"       # 资产数据
SYNC_PREFIX = "asset:sync:"  # 同步状态

# GitHub 权限范围
GITHUB_SCOPES = ["repo:read", "repo:write"]
```

---

## 7. 部署架构

### 7.1 单机部署

```
┌─────────────────────────────────────┐
│         单个服务器                   │
│  ┌─────────────────────────────┐    │
│  │   Sync Service (单进程)      │    │
│  │   • 轮询模式                 │    │
│  │   • 或 Webhook 模式          │    │
│  └──────────┬──────────────────┘    │
└─────────────┼───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│         Redis (本地)                 │
└─────────────────────────────────────┘
```

### 7.2 高可用部署

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
│                      Redis Cluster / Sentinel                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Master     │  │   Replica    │  │   Replica    │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
```

### 7.3 容器化部署

```yaml
# docker-compose.yml
version: '3.8'

services:
  sync-service:
    build: .
    environment:
      - REDIS_HOST=redis
      - GITHUB_TOKEN=${GITHUB_TOKEN}
    depends_on:
      - redis
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    restart: unless-stopped

volumes:
  redis_data:
```

---

## 8. 可观测性

### 8.1 日志系统

已实现的功能：

```python
from sync_service import Logger, setup_logging

# 初始化彩色日志
setup_logging(level="INFO", use_colors=True)

# 创建日志记录器
logger = Logger("sync_service")

# 基础日志
logger.info("Sync started", module="github")

# 带模块的日志
logger.error("Sync failed", module="redis")
```

**特性**：
- ✅ 彩色终端输出 (`ColorFormatter`)
- ✅ 文件日志轮转 (`RotatingFileHandler`)
- ✅ Redis Stream 实时推送 (`RedisStreamHandler`)
- ✅ K8s 环境自动适配

**日志格式**：
```
2025-01-15 10:30:00 | sync_service           | INFO     | Sync started
```

### 8.2 Redis Stream 实时日志

```python
from sync_service.redis_client import RedisStreamHandler

# 添加 Redis Stream Handler
handler = RedisStreamHandler(
    redis_client=redis,
    project_id="asset-library",
    max_history=100
)
logging.getLogger().addHandler(handler)

# 日志会实时推送到 Redis
# Pub/Sub: logs:stream:{p:asset-library}:{entity_id}
# History: logs:history:{p:asset-library}:{entity_id}
```

### 8.3 指标 (规划)

```python
# Prometheus 指标 (未来实现)
sync_duration_seconds = Histogram('sync_duration_seconds')
sync_total = Counter('sync_total', ['status'])
assets_synced = Gauge('assets_synced')
github_api_remaining = Gauge('github_api_rate_limit_remaining')
```

### 8.4 追踪

| 追踪项 | 实现方式 | 状态 |
|--------|----------|------|
| 同步状态 | Redis `asset:sync:state` | ✅ |
| 变更历史 | Redis `asset:sync:changed` | ✅ |
| 实时日志 | Redis Stream `logs:stream:*` | ✅ |
| 错误追踪 | 文件日志 + Sentry (规划) | 📋 |

---

## 9. 扩展性设计

### 9.1 搜索功能 (规划)

```
# Redis Search 索引
FT.CREATE asset_index ON HASH PREFIX 1 asset:metadata: SCHEMA
  id TEXT
  name TEXT
  description TEXT
  category TAG
  version TEXT
```

### 9.2 版本历史 (规划)

```
Key: asset:history:{id}:{version}
Type: Hash
Fields:
  ├─ manifest: 完整 manifest
  ├─ commit_sha: 对应的 commit SHA
  ├─ created_at: 创建时间
  └─ author: 作者
```

### 9.3 多租户 (规划)

```
# 租户隔离
asset:{tenant_id}:metadata:{id}
asset:{tenant_id}:index
asset:{tenant_id}:sync:state
```

---

## 10. 高可用与容错设计

> 本章节基于 Gemini AI 的架构评审建议

### 10.1 并发控制 (分布式锁)

**问题**：多实例部署时，可能出现多个同步进程同时运行，导致数据冲突。

**解决方案**：使用 Redis 实现分布式锁

```python
def sync_with_lock(redis_client):
    """带分布式锁的同步操作"""
    lock_key = "asset:sync:lock"
    lock_value = f"{os.getpid()}:{time.time()}"

    # 尝试获取锁，过期时间 60 秒
    lock = redis_client.set(lock_key, lock_value, nx=True, ex=60)

    if not lock:
        logger.warning("Sync already in progress, skipping")
        return SyncStats(skipped=True, errors=["Sync already in progress"])

    try:
        # 执行同步
        return sync_from_github()
    finally:
        # 释放锁（只释放自己获取的锁）
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        redis_client.eval(lua_script, 1, lock_key, lock_value)
```

**Redis 状态扩展**：
```
Key:    asset:sync:lock
Type:   String
TTL:    60 秒（自动过期）
Value:  "{process_id}:{timestamp}"
```

### 10.2 GitHub API 限流保护

**问题**：GitHub PAT 每小时有 5000 次请求限制，全量扫描可能触发限制。

**解决方案**：

```python
class GitHubManager:
    def __init__(self, config):
        self.token = config.token
        self.rate_limit_remaining = 5000
        self.rate_limit_reset = None

    def _check_rate_limit(self, response):
        """检查并更新 API 限流状态"""
        self.rate_limit_remaining = int(response.headers.get("X-RateLimit-Remaining", 0))
        self.rate_limit_reset = int(response.headers.get("X-RateLimit-Reset", 0))

        if self.rate_limit_remaining < 100:
            logger.warning(f"GitHub API rate limit low: {self.rate_limit_remaining} remaining")

        if self.rate_limit_remaining == 0:
            wait_time = self.rate_limit_reset - time.time() + 1
            logger.warning(f"Rate limit exceeded, waiting {wait_time}s")
            time.sleep(wait_time)
```

**配置项**：
```yaml
github:
  rate_limit_threshold: 100    # 剩余请求数低于此值时告警
  enable_graphql: false         # 未来：使用 GraphQL 减少 API 调用
```

### 10.3 冲突处理 (乐观锁)

**问题**：用户在 UI 修改资产时，开发者可能同时在 Git 提交了变更。

**解决方案**：使用 GitHub 文件 SHA 作为版本锚点

```python
def update_asset_with_conflict_detection(asset_id, manifest_data, author):
    """带冲突检测的资产更新"""
    # 1. 获取当前资产和 SHA
    existing = github.get_asset_by_id(asset_id)
    old_sha = existing.github_sha

    # 2. 尝试更新（传入旧 SHA）
    try:
        success, result = github.save_to_github(
            asset_id=asset_id,
            manifest_data=manifest_data,
            sha=old_sha,  # GitHub 会验证 SHA
            commit_message=f"Update asset: {asset_id}"
        )
        return True, result
    except GithubException as e:
        if e.status == 409:  # Conflict
            # 获取最新版本并返回冲突信息
            latest = github.get_asset_by_id(asset_id)
            return False, {
                "error": "CONFLICT",
                "message": "资产已被他人修改，请刷新后重试",
                "current_version": {
                    "version": latest.version,
                    "updated_at": latest.updated_at,
                    "github_sha": latest.github_sha
                }
            }
        raise
```

### 10.4 失败重试机制

**问题**：Webhook 异步触发时，如果同步失败可能丢失事件。

**解决方案**：失败队列 + 指数退避重试

```python
class SyncRetryQueue:
    """同步重试队列"""

    def add_failure(self, sync_type, error, retry_count=0):
        """添加失败记录"""
        retry_data = {
            "type": sync_type,
            "error": str(error),
            "retry_count": retry_count,
            "created_at": time.time()
        }
        redis.lpush("asset:sync:retry_queue", json.dumps(retry_data))

    def process_retries(self):
        """处理重试队列"""
        while True:
            item = redis.rpop("asset:sync:retry_queue")
            if not item:
                break

            retry_data = json.loads(item)
            retry_count = retry_data["retry_count"]

            if retry_count >= 3:  # 最多重试 3 次
                logger.error(f"Retry exhausted: {retry_data}")
                continue

            # 指数退避
            wait_time = 2 ** retry_count
            time.sleep(wait_time)

            # 重试
            try:
                if retry_data["type"] == "incremental_sync":
                    incremental_sync()
            except Exception as e:
                self.add_failure("incremental_sync", e, retry_count + 1)
```

**Redis 状态**：
```
Key:    asset:sync:retry_queue
Type:   List
TTL:    86400 (24 小时)
```

---

## 11. 开发路线图

### 11.1 已完成 (v1.0)

| 功能 | 状态 | 说明 |
|------|------|------|
| CLI 工具 | ✅ | 完整的命令行接口 |
| 全量同步 | ✅ | GitHub → Redis 完整同步 |
| 增量同步 (SHA 检测) | ✅ | Commit SHA 变更检测 |
| 全局轻量索引 | ✅ | asset:index 优化前端查询 |
| 原子性 Redis 操作 | ✅ | Pipeline 事务保证一致性 |
| 彩色日志 | ✅ | ColorFormatter + RedisStreamHandler |

### 11.2 开发中 (v1.1)

| 功能 | 优先级 | 状态 | 说明 |
|------|--------|------|------|
| **分布式锁** | 🔴 高 | 📋 规划中 | 防止并发同步冲突 |
| Webhook 服务器 | 🟡 中 | 🚧 设计完成 | 实时同步触发 |
| 单元测试 | 🟡 中 | 📋 规划中 | 核心模块测试覆盖 |

### 11.3 规划中 (v1.2)

| 功能 | 优先级 | 来源 | 说明 |
|------|--------|------|------|
| **GitHub API 限流** | 🟡 中 | Gemini 建议 | 防止配额耗尽 |
| **冲突处理** | 🟡 中 | Gemini 建议 | Git 变更冲突提示 |
| **失败重试队列** | 🟢 低 | Gemini 建议 | 异步同步可靠性 |
| HTTP API | 🟡 中 | 产品需求 | REST API 服务 |

### 11.4 长期规划 (v2.0)

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 搜索功能 | 高 | Redis Search 全文搜索 |
| 版本历史追踪 | 中 | 资产变更历史 |
| Prometheus 指标 | 中 | 云原生监控 |
| 多租户支持 | 低 | 租户隔离 |
| 资产市场 UI | 低 | 前端展示 |

---

## 附录

### A. 相关文档

| 文档 | 说明 |
|------|------|
| [TECHNICAL_GUIDE.md](TECHNICAL_GUIDE.md) | 技术详解 |
| [REDIS_KEY_CONVENTION.md](REDIS_KEY_CONVENTION.md) | Redis 规范 |
| [WEBHOOK_DESIGN.md](WEBHOOK_DESIGN.md) | Webhook 设计 |
| [DESIGN.md](DESIGN.md) | 架构升级提案 |

### B. 参考资料

- [GitHub REST API](https://docs.github.com/en/rest)
- [Redis 命令参考](https://redis.io/commands/)
- [JSON Schema 规范](https://json-schema.org/)
- [Semantic Versioning](https://semver.org/)

### C. 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v2.1.0 | 2025-01-15 | 修复 Manifest 字段；添加高可用设计章节 |
| v2.0.0 | 2025-01-10 | 整合所有设计，添加完整架构 |
| v1.1.0 | 2024-12-01 | 添加全局索引、SHA 检测 |
| v1.0.0 | 2024-11-01 | 初始版本 |

### D. 评审记录

| 评审者 | 日期 | 评分 | 主要建议 |
|--------|------|------|----------|
| Gemini AI | 2025-01-15 | 92/100 | 分布式锁、API限流、冲突处理、重试机制 |

---

*本文档由 AutoSeek Team 维护，如有疑问请联系维护者。*
