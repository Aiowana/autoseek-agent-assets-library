# Agent 资产库同步服务 - 技术详解

## 目录

1. [系统概述](#1-系统概述)
2. [架构设计](#2-架构设计)
3. [核心协议](#3-核心协议)
4. [数据结构](#4-数据结构)
5. [组件详解](#5-组件详解)
6. [同步流程](#6-同步流程)
7. [使用指南](#7-使用指南)
8. [配置说明](#8-配置说明)

---

## 1. 系统概述

### 1.1 目标

构建一个"Agent 操作系统"平台的核心同步服务，实现：

- **GitHub 仓库** 作为资产库的单一事实来源（Single Source of Truth）
- **Redis/Tendis** 作为元数据存储，供前端快速查询
- **双向同步**：GitHub → Redis（读取）、UI → GitHub（写入）

### 1.2 核心价值

```
开发者                    系统                    用户
  │                        │                        │
  │   push 代码            │                        │
  ├──────────────────────→│                        │
  │                        │                        │
  │                        │   同步服务             │
  │                        │   自动扫描             │
  │                        │                        │
  │                        │   存入 Redis           │
  │                        │───────────────────────→│
  │                        │                        │  前端展示
  │                        │                        │
  │                        │←───────────────────────│
  │                        │   用户配置             │
  │                        │                        │
  │                        │   写回 GitHub          │
  │←───────────────────────│                        │
  │                        │                        │
```

---

## 2. 架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         GitHub Repository                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                  │
│  │   tools/    │  │  prompts/   │  │   skills/   │                  │
│  │             │  │             │  │             │                  │
│  │ tool_a/     │  │ prompt_x/   │  │ skill_m/    │                  │
│  │   └manifest │  │   └manifest │  │   └manifest │                  │
│  │             │  │             │  │             │                  │
│  │ tool_b/     │  │ prompt_y/   │  │ skill_n/    │                  │
│  │   └manifest │  │   └manifest │  │   └manifest │                  │
│  └─────────────┘  └─────────────┘  └─────────────┘                  │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              │ GitHub REST API
                              │ (PyGithub)
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Sync Service (Python)                          │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    AssetSyncService                         │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │    │
│  │  │GitHubManager │  │   Validator  │  │ RedisClient  │      │    │
│  │  │              │  │              │  │              │      │    │
│  │  │ 扫描仓库     │  │ 校验 YAML    │  │ 存储元数据   │      │    │
│  │  │ 解析文件     │  │ Schema验证   │  │ 维护索引     │      │    │
│  │  │ 写回 GitHub │  │              │  │ 状态管理     │      │    │
│  │  └──────────────┘  └──────────────┘  └──────────────┘      │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              │ RESP (Redis Protocol)
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         Redis / Tendis                             │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  asset:metadata:{id}          ──→  Hash (资产元数据)         │    │
│  │  asset:category:{category}    ──→  Set  (分类索引)          │    │
│  │  asset:sync:state             ──→  Hash (同步状态)          │    │
│  │  asset:sync:changed           ──→  List (变更记录)          │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 模块依赖关系

```
main.py
  │
  ├─→ Config (配置管理)
  │     └─→ RedisConfig, GitHubConfig, SyncConfig
  │
  ├─→ RedisClient (Redis 操作)
  │     └─→ pipeline 事务、索引维护
  │
  ├─→ ManifestValidator (校验器)
  │     └─→ JSON Schema 校验
  │
  ├─→ GitHubManager (GitHub 操作)
  │     ├─→ 扫描仓库 (scan_manifests)
  │     ├─→ 解析文件 (parse_manifest)
  │     └─→ 写回 GitHub (save_to_github)
  │
  └─→ AssetSyncService (同步编排)
        ├─→ sync_from_github()      (全量同步)
        ├─→ incremental_sync()      (增量同步)
        ├─→ create_asset()          (创建资产)
        ├─→ update_asset()          (更新资产)
        └─→ delete_asset()          (删除资产)
```

---

## 3. 核心协议

### 3.1 manifest.yaml 标准

所有资产必须包含 `manifest.yaml` 文件，遵循以下结构：

```yaml
# ========== 基础元数据 ==========
id: "unique_asset_id"              # 唯一标识符
version: "1.0.0"                    # 语义化版本号
category: "tool"                    # 类别: tool | prompt | skill
name: "Display Name"                # 展示名称
description: "Asset description"    # 功能描述
author: "Author Name"               # 作者

# ========== 前端表单配置 ==========
config_schema:
  - name: "param_key"               # 变量名
    label: "参数名"                  # 前端显示标签
    type: "string"                  # 类型: string|number|select|secret|boolean
    required: true                  # 是否必填
    default: null                   # 默认值
    placeholder: "提示文字"
    # options:                       # select 类型专用
    #   - { label: "选项A", value: "A" }

# ========== LLM Function Calling 定义 ==========
agent_specs:
  function_name: "call_name"        # 函数名
  description: "告诉 AI 何时调用此工具"
  parameters:                       # JSON Schema 格式
    type: "object"
    properties:
      input_param:
        type: "string"
        description: "参数说明"
    required: ["input_param"]

# ========== 运行时配置 ==========
runtime:
  language: "python"                # 编程语言
  entry: "main.py"                  # 入口文件
  handler: "main_handler"           # 入口函数
  dependencies:                     # pip 依赖
    - "requests>=2.31.0"

# ========== 权限配置 ==========
permissions:
  network_access: true              # 是否允许网络访问
  filesystem_read: false            # 是否允许读取文件
```

### 3.2 JSON Schema 定义

系统使用 `jsonschema` 库进行校验，核心规则：

| 字段 | 校验规则 |
|------|----------|
| `id` | 正则: `^[a-zA-Z0-9_-]+$` |
| `version` | 正则: `^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$` (semver) |
| `category` | 枚举: `tool`, `prompt`, `skill` |
| `config_schema[].type` | 枚举: `string`, `number`, `select`, `secret`, `boolean` |
| `runtime.language` | 枚举: `python` |

---

## 4. 数据结构

### 4.1 Redis 数据结构

#### 元数据存储 (Hash)
```
Key: asset:metadata:{asset_id}
Type: Hash
Fields:
  ├─ id              # 资产 ID
  ├─ version         # 版本号
  ├─ category        # 类别
  ├─ name            # 名称
  ├─ description     # 描述
  ├─ config_schema   # JSON 字符串
  ├─ agent_specs     # JSON 字符串 (可选)
  ├─ runtime         # JSON 字符串 (可选)
  ├─ author          # 作者 (可选)
  ├─ github_path     # GitHub 文件路径
  ├─ github_sha      # GitHub 文件 SHA
  ├─ created_at      # 创建时间戳
  └─ updated_at      # 更新时间戳
```

#### 分类索引 (Set)
```
Key: asset:category:{category}
Type: Set
Members: 资产 ID 集合

示例:
  asset:category:tool    → {"http_request", "web_scraper", ...}
  asset:category:prompt  → {"text_summarizer", "translator", ...}
  asset:category:skill   → {"data_analysis", "report_gen", ...}
```

#### 同步状态 (Hash)
```
Key: asset:sync:state
Type: Hash
Fields:
  ├─ last_sync_time   # 上次同步时间戳
  ├─ last_sync_sha    # 上次同步的 commit SHA (预留)
  ├─ synced_count     # 已同步资产总数
  └─ sync_status      # 同步状态: idle | syncing | failed
```

#### 变更记录 (List)
```
Key: asset:sync:changed
Type: List
Members: 变更的资产 ID (按时间顺序)
```

### 4.2 代码数据模型

```python
# 数据流转链路
GitHubFile
  ├─ path: str           # 文件路径
  ├─ content: str        # YAML 原文
  ├─ sha: str            # GitHub SHA
  └─ download_url: str
       │
       │ yaml.safe_load()
       ▼
Dict (原始数据)
  └─ {"id": "xxx", "version": "1.0.0", ...}
       │
       │ ManifestValidator.validate_and_parse()
       ▼
ManifestData (Pydantic Model)
  ├─ id: str
  ├─ version: str
  ├─ category: Literal["tool", "prompt", "skill"]
  ├─ config_schema: List[ConfigSchemaItem]
  └─ ...
       │
       │ 封装为 Asset
       ▼
Asset
  ├─ manifest: ManifestData
  ├─ github_path: str
  ├─ github_sha: str
  └─ github_url: str
       │
       │ asset.to_stored_asset()
       ▼
StoredAsset
  ├─ id: str
  ├─ config_schema: str  # JSON 字符串
  ├─ agent_specs: str    # JSON 字符串
  ├─ runtime: str        # JSON 字符串
  └─ ...
       │
       │ stored.to_dict()
       ▼
Dict (Redis Hash 格式)
  └─ {"id": "xxx", "config_schema": "[...]", ...}
       │
       │ redis.hset()
       ▼
Redis Hash
```

---

## 5. 组件详解

### 5.1 Config - 配置管理

**职责**: 统一管理所有配置项

**加载方式**:
```python
# 从 YAML 文件加载
config = Config.from_yaml("settings.yaml")

# 从环境变量加载
config = Config.from_env()
```

**配置层级**: 环境变量 > YAML 文件 > 默认值

### 5.2 RedisClient - Redis 操作封装

**职责**: 封装所有 Redis 操作，实现 Key 管理和事务

**核心方法**:

| 方法 | 功能 |
|------|------|
| `save_asset_atomic()` | 原子性写入资产 (使用 Pipeline) |
| `get_asset()` | 获取单个资产 |
| `delete_asset_atomic()` | 原子性删除资产 |
| `add_to_category()` | 添加到分类索引 |
| `get_by_category()` | 按分类获取资产 ID |
| `set_sync_status()` | 更新同步状态 |
| `add_changed_asset()` | 记录变更资产 |

**原子性保证**:
```python
pipeline = redis.pipeline()
pipeline.hset(f"asset:metadata:{id}", mapping=data)
pipeline.sadd(f"asset:category:{category}", id)
pipeline.execute()  # 要么全成功，要么全失败
```

### 5.3 ManifestValidator - 校验器

**职责**: 校验 manifest.yaml 是否符合协议

**校验流程**:
```
1. yaml.safe_load() 解析 YAML
2. jsonschema.validate() 校验结构
3. Pydantic 解析为类型安全的 Model
4. 返回 ManifestData 或抛出 ValidationError
```

### 5.4 GitHubManager - GitHub 操作

**职责**: 封装 GitHub API 操作

**核心方法**:

| 方法 | 功能 |
|------|------|
| `scan_manifests()` | 递归扫描仓库，查找所有 manifest.yaml |
| `parse_manifest()` | 解析并校验单个 manifest 文件 |
| `fetch_and_parse_all()` | 批量获取并解析所有资产 |
| `save_to_github()` | 创建/更新 GitHub 文件 |
| `delete_from_github()` | 删除 GitHub 文件 |
| `get_latest_commit_sha()` | 获取最新 commit SHA |
| `get_commits_since()` | 获取指定时间后的提交 |

**递归扫描逻辑**:
```python
def scan_manifests(self):
    contents = repo.get_contents(base_path)
    while contents:
        file = contents.pop(0)
        if file.type == "dir":
            contents.extend(repo.get_contents(file.path))  # 递归
        elif is_manifest(file.name):
            manifests.append(fetch_file(file))
```

### 5.5 AssetSyncService - 同步编排

**职责**: 协调各组件完成同步逻辑

**核心方法**:

| 方法 | 功能 |
|------|------|
| `sync_from_github()` | 全量同步 (GitHub → Redis) |
| `incremental_sync()` | 增量同步 (基于时间戳) |
| `create_asset()` | 创建资产 (UI → GitHub → Redis) |
| `update_asset()` | 更新资产 |
| `delete_asset()` | 删除资产 |
| `health_check()` | 健康检查 |

---

## 6. 同步流程

### 6.1 全量同步流程 (sync_from_github)

```
┌─────────────────────────────────────────────────────────────┐
│ 1. 扫描 GitHub 仓库                                         │
│    github_manager.scan_manifests()                          │
│    └─→ 递归遍历目录，查找 manifest.yaml                      │
│    └─→ 获取文件内容和 SHA                                   │
│    └─→ 返回 List[GitHubFile]                                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. 解析并校验                                               │
│    对每个 GitHubFile:                                       │
│    ├─ yaml.safe_load(content)  → Dict                      │
│    ├─ validator.validate_and_parse() → ManifestData        │
│    └─ 封装为 Asset 对象                                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. 差异检测                                                 │
│    ├─ 从 Redis 获取已有资产: existing_assets                │
│    ├─ 对比 GitHub 资产 vs Redis 资产:                       │
│    │   ├─ 新资产: GitHub 有，Redis 无 → CREATE             │
│    │   ├─ 更新: SHA 不同 → UPDATE                          │
│    │   ├─ 删除: GitHub 无，Redis 有 → DELETE               │
│    │   └─ 无变化: SHA 相同 → SKIP                          │
│    └─ 返回变更列表                                          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. 写入 Redis (原子操作)                                    │
│    对需要变更的资产:                                        │
│    ├─ 转换为 StoredAsset (JSON 序列化)                      │
│    ├─ redis.save_asset_atomic()                             │
│    │   ├─ Pipeline 事务:                                   │
│    │   │   ├─ HSET asset:metadata:{id}                     │
│    │   │   ├─ SADD asset:category:{category}               │
│    │   │   └─ SREM 旧分类 (如果分类变更)                    │
│    │   └─ EXEC                                             │
│    └─ 记录到变更队列: RPUSH asset:sync:changed              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. 更新同步状态                                             │
│    ├─ SET last_sync_time = now()                           │
│    ├─ SET synced_count = total_count                       │
│    ├─ SET sync_status = "idle"                             │
│    └─ 返回 SyncStats                                        │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 增量同步流程 (incremental_sync)

```
1. 获取 last_sync_time from Redis
2. 如果没有历史记录 → 执行全量同步
3. 调用 GitHub API: /commits?since={timestamp}
4. 如果有新提交 → 执行全量同步 (简化实现)
5. 如果无新提交 → 跳过同步
```

> **注意**: 当前增量同步仍执行全量扫描。真正的增量同步需要解析 commit diff，只处理变更的文件（后续优化）。

### 6.3 差异检测逻辑

```python
def _should_update_asset(asset: Asset, existing: Optional[StoredAsset]) -> bool:
    if existing is None:
        return True  # 新资产

    if existing.github_sha != asset.github_sha:
        return True  # 文件内容变更 (最可靠)

    if existing.version != asset.version:
        return True  # 版本号变更

    return False  # 无变化
```

### 6.4 反向写入流程 (UI → GitHub)

```
用户在 UI 修改配置
        │
        ▼
前端发送 HTTP 请求
        │
        ▼
┌───────────────────────────────────────┐
│ 后端接收请求                          │
│ 1. 校验 manifest 数据                 │
│ 2. 调用 sync_service.create_asset()   │
└───────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────┐
│ 写入 GitHub                          │
│ github_manager.save_to_github()       │
│  1. 序列化为 YAML                     │
│  2. GitHub API 创建/更新文件          │
│  3. 获取新的 SHA                      │
└───────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────┐
│ 同步回 Redis                         │
│ 1. 重新解析 GitHub 文件               │
│ 2. 更新 Redis 中的元数据              │
│ 3. 返回成功给前端                     │
└───────────────────────────────────────┘
```

---

## 7. 使用指南

### 7.1 安装

```bash
# 克隆仓库
git clone <repository-url>
cd autoseek-agent-assets-library

# 安装依赖
pip install -r requirements.txt

# 复制配置文件
cp settings.yaml.example settings.yaml
cp .env.example .env

# 编辑配置
vim .env
```

### 7.2 配置

**环境变量 (.env)**:
```bash
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_DB=0

GITHUB_TOKEN=ghp_xxxxxxxxxxxx
GITHUB_REPO=owner/repository
GITHUB_BRANCH=main

SYNC_INTERVAL=300
LOG_LEVEL=INFO
```

**配置文件 (settings.yaml)**:
```yaml
redis:
  host: "localhost"
  port: 6379
  password: null
  db: 0

github:
  token: ""  # 从环境变量读取
  repo: "owner/repo"
  branch: "main"
  base_path: ""

sync:
  interval_seconds: 300
  batch_size: 100
  enable_incremental: true
```

### 7.3 命令行使用

```bash
# 全量同步
python main.py sync

# 增量同步
python main.py sync --incremental

# 持续同步 (轮询模式)
python main.py sync --continuous

# 健康检查
python main.py health

# 列出所有资产
python main.py list

# 按分类筛选
python main.py list --category tool

# 查看资产详情
python main.py get http_request

# 详细输出
python main.py sync --verbose
```

### 7.4 代码使用

```python
from sync_service import Config, RedisClient, GitHubManager, ManifestValidator, AssetSyncService

# 加载配置
config = Config.from_yaml("settings.yaml")

# 初始化组件
redis = RedisClient(config.redis)
validator = ManifestValidator()
github = GitHubManager(config.github, validator)
service = AssetSyncService(config, redis, github)

# 执行同步
stats = service.sync_from_github()
print(f"Created: {stats.created}, Updated: {stats.updated}")

# 查询资产
asset = service.get_asset("http_request")
print(asset.name, asset.version)

# 按分类查询
tools = service.get_assets_by_category("tool")
for tool in tools:
    print(f"  {tool.id}: {tool.name}")

# 创建资产
manifest_data = {
    "id": "new_tool",
    "version": "1.0.0",
    "category": "tool",
    "name": "新工具",
    "description": "描述",
    ...
}
success, result = service.create_asset(manifest_data, author="Your Name")
```

---

## 8. 配置说明

### 8.1 RedisConfig

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `host` | str | "localhost" | Redis 主机 |
| `port` | int | 6379 | Redis 端口 |
| `password` | str | None | Redis 密码 |
| `db` | int | 0 | Redis 数据库编号 |
| `decode_responses` | bool | True | 自动解码响应 |

### 8.2 GitHubConfig

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `token` | str | **必填** | GitHub Personal Access Token |
| `repo` | str | **必填** | 仓库地址 (格式: owner/repo) |
| `branch` | str | "main" | 分支名 |
| `base_path` | str | "" | 扫描起始路径 (空表示从根目录) |

### 8.3 SyncConfig

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `interval_seconds` | int | 300 | 持续同步间隔 |
| `batch_size` | int | 100 | 批处理大小 |
| `enable_incremental` | bool | True | 是否启用增量同步 |
| `max_retries` | int | 3 | 最大重试次数 |
| `retry_delay` | int | 5 | 重试延迟 (秒) |

---

## 9. 故障排查

### 9.1 常见问题

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| `Failed to load configuration` | settings.yaml 不存在 | 从 example 复制或使用环境变量 |
| `GitHub token is required` | 未设置 GITHUB_TOKEN | 在 .env 中配置 |
| `Asset validation failed` | manifest.yaml 格式错误 | 检查 YAML 格式和必需字段 |
| `Redis connection refused` | Redis 未启动 | 启动 Redis 服务 |

### 9.2 日志级别

```python
# 修改日志级别
export LOG_LEVEL=DEBUG  # DEBUG, INFO, WARNING, ERROR
```

---

## 10. 版本信息

- **当前版本**: v1.0.0
- **Python 要求**: 3.10+
- **核心依赖**: redis, PyGithub, pyyaml, jsonschema, pydantic

---

*文档最后更新: 2024-01-01*
