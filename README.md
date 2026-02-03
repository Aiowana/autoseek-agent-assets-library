# Agent Asset Library Sync Service

资产库同步服务，用于在 GitHub 仓库和 Redis/Tendis 之间双向同步 Agent 资产元数据。

## 架构说明

```
GitHub Repository (资产库)
    ↓
Sync Service (本服务)
    ↓
Redis/Tendis (元数据存储)
```

### 核心协议

所有资产必须包含 `manifest.yaml` 文件，遵循以下结构：

```yaml
id: "unique_asset_id"
version: "1.0.0"
category: "tool"  # tool | prompt | skill
name: "Display Name"
description: "Asset description"
author: "Author Name"

# 前端表单配置
config_schema:
  - name: "param_key"
    label: "参数名"
    type: "string"  # string | number | select | secret | boolean
    required: true

# LLM Function Calling 定义
agent_specs:
  function_name: "call_name"
  description: "Tell LLM when to use this"
  parameters:
    type: "object"
    properties: {...}

# 运行时配置
runtime:
  language: "python"
  entry: "main.py"
  handler: "main_handler"
  dependencies: []

# 权限配置
permissions:
  network_access: true
  filesystem_read: false
```

## 安装

```bash
# 安装依赖
pip install -r requirements.txt

# 复制配置文件
cp settings.yaml.example settings.yaml
cp .env.example .env

# 编辑配置，填入必要信息
# - GitHub Token
# - Redis 连接信息
# - GitHub 仓库地址
```

## 配置

### 环境变量 (`.env`)

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

### 配置文件 (`settings.yaml`)

```yaml
redis:
  host: "localhost"
  port: 6379
  password: null
  db: 0

github:
  token: ""  # 从环境变量读取
  repo: "owner/repository"
  branch: "main"
  base_path: ""  # 空表示从根目录扫描

sync:
  interval_seconds: 300
  batch_size: 100
  enable_incremental: true
```

## 使用

### 1. 一次性同步

```bash
python main.py sync
```

### 2. 增量同步

```bash
python main.py sync --incremental
```

### 3. 持续同步（轮询模式）

```bash
python main.py sync --continuous
```

### 4. 健康检查

```bash
python main.py health
```

### 5. 列出资产

```bash
# 列出所有资产
python main.py list

# 按分类筛选
python main.py list --category tool
```

### 6. 查看资产详情

```bash
python main.py get <asset_id>
```

## 文档

| 文档 | 说明 |
|------|------|
| [README.md](README.md) | 项目说明和快速开始 |
| [TECHNICAL_GUIDE.md](TECHNICAL_GUIDE.md) | 技术详解，包含架构、流程、API |
| [REDIS_KEY_CONVENTION.md](REDIS_KEY_CONVENTION.md) | Redis Key 命名规范 |
| [DESIGN.md](DESIGN.md) | 设计文档 |

## Redis 数据结构

详见 [REDIS_KEY_CONVENTION.md](REDIS_KEY_CONVENTION.md)

```
asset:metadata:{id}          # Hash: 资产元数据
asset:category:{category}    # Set: 分类索引
asset:sync:state             # Hash: 同步状态
asset:sync:changed           # List: 变更记录
```

## 项目结构

```
.
├── main.py                  # 命令行入口
├── requirements.txt         # Python 依赖
├── settings.yaml.example    # 配置示例
├── .env.example             # 环境变量示例
├── sync_service/            # 核心模块
│   ├── __init__.py
│   ├── config.py            # 配置管理
│   ├── models.py            # 数据模型
│   ├── redis_client.py      # Redis 操作封装
│   ├── schema.py            # JSON Schema 校验
│   ├── github_manager.py    # GitHub API 封装
│   └── sync_service.py      # 主同步逻辑
├── DESIGN.md                # 设计文档
├── REDIS_KEY_CONVENTION.md  # Redis Key 规范
├── TECHNICAL_GUIDE.md       # 技术详解
└── README.md                # 本文档
```

## 开发计划

- [ ] 添加 HTTP API 服务器模式
- [ ] 支持从 UI 创建/更新资产（反向写入 GitHub）
- [ ] 添加搜索索引功能
- [ ] 实现资产版本历史追踪
- [ ] 添加 Webhook 支持（GitHub 推送触发同步）
