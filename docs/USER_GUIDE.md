# Agent 资产库 - 用户完整指南

## 文档信息

| 项目 | 说明 |
|------|------|
| **文档版本** | v1.0.0 |
| **最后更新** | 2026-03-04 |
| **适用系统** | Agent Asset Library v2.0+ (多租户版本) |

---

## 目录

1. [系统概述](#1-系统概述)
2. [快速开始](#2-快速开始)
3. [账户创建与接入](#3-账户创建与接入)
4. [工具创建完整流程](#4-工具创建完整流程)
5. [高级功能](#5-高级功能)
6. [API 参考](#6-api-参考)
7. [故障排查](#7-故障排查)
8. [FAQ](#8-faq)

---

## 1. 系统概述

### 1.1 什么是 Agent 资产库？

Agent 资产库是一个**多租户 SaaS 平台**，允许用户创建、管理和分享 AI Agent 组件：

- **工具 (Tools)**: AI Agent 可调用的外部功能
- **提示词 (Prompts)**: 结构化的提示词模板
- **技能 (Skills)**: 复杂的组合能力

### 1.2 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户层                                    │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│   │ 项目 A   │  │ 项目 B   │  │ 用户 Alice│  │ 组织 XYZ  │       │
│   └─────┬────┘  └─────┬────┘  └─────┬────┘  └─────┬────┘       │
└─────────┼─────────────┼─────────────┼─────────────┼──────────────┘
          │             │             │             │
          └─────────────┴─────────────┴─────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Web 界面 / API                              │
│   • 工具编辑器    • 草稿管理    • 预览发布    • 团队协作         │
└─────────────────────────────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    多租户同步服务                                │
│   • 按租户隔离   • Git 同步    • Webhook 触发   • 版本管理       │
└─────────────────────────────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    存储层                                        │
│   Redis (缓存/索引)  ←→  GitHub (源码仓库)                      │
└─────────────────────────────────────────────────────────────────┘
```

### 1.3 核心概念

| 概念 | 说明 | 示例 |
|------|------|------|
| **租户 (Tenant)** | 独立的工作空间，完全隔离 | `proj_alpha`、`user_alice` |
| **命名空间 (Namespace)** | Redis 数据隔离前缀 | `asset:user_alice:*` |
| **资产 (Asset)** | 工具、提示词或技能 | `weather_checker` |
| **清单 (Manifest)** | 资产的配置文件 | `manifest.yaml` |

---

## 2. 快速开始

### 2.1 5 分钟快速体验

```bash
# 1. 克隆示例仓库
git clone https://github.com/example/agent-assets-demo.git
cd agent-assets-demo

# 2. 创建一个简单的工具
mkdir -p tools/hello_world
cat > tools/hello_world/manifest.yaml << 'EOF'
id: hello_world
name: 世界你好
version: 1.0.0
category: tool
description: 向世界打招呼的简单工具

author: Your Name
tags: [demo, hello]

parameters:
  name:
    type: string
    description: 要问候的名字
    required: true
    default: "世界"

examples:
  - input: {name: "Alice"}
    output: {message: "你好，Alice！"}
EOF

# 3. 提交到 Git
git add .
git commit -m "feat: 添加问候工具"
git push origin main

# 4. 工具自动同步上线（Webhook 触发）
# 5. 在 AI Agent 中调用工具
```

### 2.2 你需要准备什么

| 项目 | 说明 | 获取方式 |
|------|------|----------|
| **GitHub 账号** | 用于托管资产代码 | https://github.com/signup |
| **Git 工具** | 本地代码管理 | https://git-scm.com/ |
| **Personal Access Token** | API 访问凭证 | GitHub Settings → Developer settings |

---

## 3. 账户创建与接入

### 3.1 账户类型

系统支持三种类型的账户：

| 类型 | 命名空间前缀 | 适用场景 | 示例 |
|------|-------------|----------|------|
| **项目账户** | `proj_` | 团队协作的项目 | `proj_alpha` |
| **个人账户** | `user_` | 个人开发者的工具库 | `user_alice` |
| **组织账户** | `org_` | 企业/组织的统一管理 | `org_acme` |

### 3.2 创建账户（租户接入）

#### 步骤 1: 准备 GitHub 仓库

```
1. 登录 GitHub
2. 创建新仓库: https://github.com/new
   - 仓库名称: agent-tools (或任意名称)
   - 可见性: Private (私有) 或 Public (公开)
   - 初始化: ✓ Add README
```

#### 步骤 2: 生成 Personal Access Token

```
1. 进入: Settings → Developer settings → Personal access tokens → Tokens (classic)
2. 点击: Generate new token (classic)
3. 配置:
   - Name: Agent Asset Library
   - Expiration: 90 days (或 No expiration)
   - 勾选权限:
     ✓ repo (Full control of private repositories)
     ✓ workflow (如果需要 GitHub Actions)
4. 点击: Generate token
5. 复制 Token (只显示一次!): ghp_xxxxxxxxxxxxxxxxxxxx
```

#### 步骤 3: 联系管理员

将以下信息发送给系统管理员：

```yaml
账户信息:
  类型: 个人账户 / 项目账户 / 组织账户
  名称: 你的显示名称
  GitHub 用户名: your-github-username
  仓库名称: your-repo-name
  分支名称: main (或 master)
  用途说明: 简短描述使用目的

管理员操作:
  1. 创建租户配置
  2. 生成 Webhook Secret
  3. 配置环境变量
  4. 执行首次同步
```

#### 步骤 4: 配置 GitHub Webhook

管理员完成配置后，你需要：

```
1. 进入你的 GitHub 仓库
2. Settings → Webhooks → Add webhook
3. 配置:
   - Payload URL: https://your-domain.com/webhook/github/your_namespace
   - Content type: application/json
   - Secret: [管理员提供的 Webhook Secret]
   - Events: ✓ Just the push event
4. 点击: Add webhook
5. 测试: 点击 "Recent Deliveries" 查看是否成功
```

### 3.3 验证接入

```bash
# 管理员执行首次同步
python main.py sync --tenant your_namespace

# 查看同步状态
python main.py tenants
```

预期输出：
```
Tenants (1):
------------------------------------------------------------
  your_namespace               你的显示名称       [enabled]
    Platform: github
    Repo: your-github-username/your-repo-name
    Branch: main
    Webhook: /webhook/github/your_namespace
```

---

## 4. 工具创建完整流程

### 4.1 流程概览

```
┌─────────────────────────────────────────────────────────────────┐
│                         工具创建流程                              │
└─────────────────────────────────────────────────────────────────┘

┌──────────┐    ┌──────────┐    ┌──────────�    ┌──────────┐
│ 本地开发  │───▶│ 推送 Git │───▶│ 自动同步  │───▶│ 工具上线  │
│          │    │          │    │          │    │          │
│ • 编辑器  │    │ git push │    │ Webhook  │    │ Redis    │
│ • manifest│    │          │    │          │    │ 可调用   │
└──────────┘    └──────────┘    └──────────┘    └──────────┘
     │                                                    │
     ▼                                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                    可选：Web UI 编辑流程                          │
│                                                                 │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │ 创建草稿  │───▶│ 编辑保存  │───▶│ 预览测试  │───▶│ 提交 Git │  │
│  │          │    │ 自动保存  │    │ YAML预览  │    │          │  │
│  │ 表单填写  │    │ Redis草稿│    │          │    │ 一键发布  │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 方式一：Git 工作流（推荐开发者）

#### 步骤 1: 克隆仓库

```bash
# 克隆你的资产仓库
git clone https://github.com/your-username/your-repo.git
cd your-repo
```

#### 步骤 2: 创建目录结构

```bash
# 创建工具目录
mkdir -p tools/my_tool

# 目录结构
your-repo/
├── tools/
│   └── my_tool/
│       └── manifest.yaml
├── prompts/          # 提示词目录
├── skills/           # 技能目录
└── README.md
```

#### 步骤 3: 编写 manifest.yaml

创建 `tools/my_tool/manifest.yaml`：

```yaml
id: my_tool
name: 我的工具
version: 1.0.0
category: tool
description: 工具的功能描述

author: Your Name <your@email.com>
tags: [tag1, tag2, tag3]
license: MIT

# 工具配置
config:
  timeout: 30
  retry: 3
  base_url: https://api.example.com

# 参数定义
parameters:
  input_param:
    type: string
    description: 输入参数描述
    required: true
    default: "default_value"
    enum: ["option1", "option2"]  # 可选值约束

# 输出定义
output:
  type: object
  properties:
    result:
      type: string
      description: 结果描述

# 使用示例
examples:
  - input: {input_param: "test"}
    output: {result: "success"}
    description: 示例说明

# 依赖声明
dependencies:
  - package: requests
    version: ">=2.28.0"
```

#### 步骤 4: 提交到 Git

```bash
# 添加文件
git add tools/my_tool/manifest.yaml

# 提交
git commit -m "feat: 添加我的工具

- 功能描述
- 参数说明
- 示例用法"

# 推送
git push origin main
```

#### 步骤 5: 自动同步上线

```
推送后，Webhook 自动触发：

1. GitHub 发送 push 事件
2. 系统接收 Webhook
3. 验证签名
4. 同步你的仓库
5. 工具自动上线

预计 10-30 秒完成
```

### 4.3 方式二：Web UI 工作流（推荐非开发者）

#### 步骤 1: 登录 Web 界面

```
访问: https://your-domain.com/

登录后进入工作台
```

#### 步骤 2: 创建新工具

```
点击: [创建工具]

填写基本信息:
┌─────────────────────────────────────────────────────────┐
│ 工具 ID:          weather_checker                        │
│ 工具名称:        天气查询工具                             │
│ 工具分类:        ○ Tool  ○ Prompt  ● Skill              │
│ 描述:            查询指定城市的实时天气信息               │
│ 标签:            weather, api, utility                   │
└─────────────────────────────────────────────────────────┘

点击: [下一步]
```

#### 步骤 3: 配置参数

```
参数定义:
┌────────────────────────────────────────────────────────────────────┐
│ [+ 添加参数]                                                        │
│                                                                    │
│ 参数 1:                                                            │
│   名称:          city                                              │
│   类型:          ▼ String                                         │
│   描述:          城市名称                                          │
│   必填:          ✓ 是                                             │
│   默认值:                                                         │
│                                                                    │
│ 参数 2:                                                            │
│   名称:          units                                            │
│   类型:          ▼ String                                         │
│   描述:          温度单位                                          │
│   必填:          □ 否                                             │
│   默认值:        celsius                                          │
│   可选值:        celsius, fahrenheit                              │
└────────────────────────────────────────────────────────────────────┘

点击: [下一步]
```

#### 步骤 4: 添加示例

```
使用示例:
┌────────────────────────────────────────────────────────────────────┐
│ [+ 添加示例]                                                        │
│                                                                    │
│ 示例 1:                                                            │
│   输入:                                                            │
│   {                                                                │
│     "city": "北京",                                                │
│     "units": "celsius"                                            │
│   }                                                                │
│                                                                    │
│   输出:                                                            │
│   {                                                                │
│     "temperature": 22,                                            │
│     "condition": "晴朗",                                           │
│     "humidity": 45                                                │
│   }                                                                │
│                                                                    │
│   说明: 查询北京的天气                                            │
└────────────────────────────────────────────────────────────────────┘

点击: [下一步]
```

#### 步骤 5: 预览与保存

```
预览 YAML:
┌────────────────────────────────────────────────────────────────────┐
│ id: weather_checker                                                │
│ name: 天气查询工具                                                 │
│ version: 1.0.0                                                     │
│ category: tool                                                     │
│ description: 查询指定城市的实时天气信息                            │
│ ...                                                                │
└────────────────────────────────────────────────────────────────────┘

[保存为草稿]    [提交到 Git]

点击: [保存为草稿]
```

#### 步骤 6: 提交发布

```
草稿已保存！

点击: [我的草稿] → 选择草稿 → [编辑] / [发布]

发布配置:
┌────────────────────────────────────────────────────────────────────┐
│ 提交信息:          feat: 添加天气查询工具                          │
│ 作者:              Alice                                           │
│                                                                    │
│ 目标位置:          tools/weather_checker/manifest.yaml             │
│                                                                    │
│ ✓ 发布后自动同步                                                   │
│ ✓ 同时更新 GitHub 仓库                                             │
└────────────────────────────────────────────────────────────────────┘

点击: [确认发布]

发布成功！工具将在 30 秒内上线。
```

### 4.4 工具 manifest 详解

#### 完整模板

```yaml
# ============================================================
# 基本信息
# ============================================================
id: unique_tool_id              # 唯一标识，只能包含字母、数字、下划线
name: 工具显示名称               # 中文名称
version: 1.0.0                  # 版本号 (semantic versioning)
category: tool                  # 类型: tool | prompt | skill
description: 详细的功能描述     # 支持 Markdown

author: Your Name               # 作者
organization: Your Company      # 组织（可选）
tags: [tag1, tag2, tag3]        # 标签，便于搜索
license: MIT                    # 许可证

# ============================================================
# 配置项
# ============================================================
config:
  timeout: 30                   # 超时时间（秒）
  retry: 3                      # 重试次数
  base_url: https://api.example.com
  headers:
    Authorization: "Bearer ${API_TOKEN}"
    User-Agent: "AgentAsset/1.0"

# ============================================================
# 环境变量
# ============================================================
environment:
  - name: API_KEY
    description: API 密钥
    required: true
  - name: API_ENDPOINT
    description: API 端点
    required: false
    default: "https://api.example.com"

# ============================================================
# 参数定义
# ============================================================
parameters:
  param1:
    type: string                 # 类型: string | number | boolean | array | object
    description: 参数描述
    required: true
    default: "default_value"
    enum: ["option1", "option2"]  # 枚举约束
    format: email                 # 格式约束: email | url | uuid | date
    pattern: "^[a-z]+$"          # 正则约束
    min_length: 1                 # 最小长度
    max_length: 100               # 最大长度

  param2:
    type: number
    description: 数字参数
    minimum: 0                    # 最小值
    maximum: 100                  # 最大值

# ============================================================
# 输出定义
# ============================================================
output:
  type: object
  description: 返回结果说明
  properties:
    result:
      type: string
      description: 结果字段
    code:
      type: integer
      description: 状态码

# ============================================================
# 使用示例
# ============================================================
examples:
  - input:
      param1: "value1"
      param2: 42
    output:
      result: "success"
      code: 200
    description: 示例说明

  - input:
      param1: "value2"
    output:
      result: "error"
      code: 400
    description: 错误示例

# ============================================================
# 依赖声明
# ============================================================
dependencies:
  runtime:
    - package: requests
      version: ">=2.28.0"
    - package: pyyaml
      version: ">=6.0"

  dev:
    - package: pytest
      version: ">=7.0"

# ============================================================
# 相关资源
# ============================================================
links:
  documentation: https://docs.example.com
  repository: https://github.com/example/tool
  issues: https://github.com/example/tool/issues

# ============================================================
# 元数据
# ============================================================
metadata:
  created_at: "2026-03-04"
  updated_at: "2026-03-04"
  contributor: Alice
  changelog:
    - version: "1.0.0"
      date: "2026-03-04"
      changes:
        - "初始版本"
```

---

## 5. 高级功能

### 5.1 草稿管理

```bash
# API 端点

# 创建草稿
POST /api/{namespace}/drafts
{
  "asset_id": "my_tool",
  "manifest": {...},
  "author": "Alice"
}

# 保存草稿
PUT /api/{namespace}/drafts/{draft_id}
{
  "manifest": {...}
}

# 获取草稿
GET /api/{namespace}/drafts/{draft_id}

# 列出所有草稿
GET /api/{namespace}/drafts?status=editing

# 删除草稿
DELETE /api/{namespace}/drafts/{draft_id}

# 预览 YAML
POST /api/{namespace}/drafts/{draft_id}/preview

# 提交到 Git
POST /api/{namespace}/drafts/{draft_id}/commit
{
  "commit_message": "feat: 添加新工具",
  "author": "Alice"
}
```

### 5.2 版本管理

```yaml
# 版本号遵循 Semantic Versioning 2.0.0
# 格式: MAJOR.MINOR.PATCH

# 示例:
version: 1.0.0    # 初始版本
version: 1.1.0    # 新增功能（向后兼容）
version: 1.0.1    # Bug 修复
version: 2.0.0    # 破坏性变更

# 更新版本时更新 changelog
metadata:
  changelog:
    - version: "2.0.0"
      date: "2026-03-04"
      changes:
        - "破坏性: 参数名从 input 改为 query"
        - "新增: 支持批量查询"
    - version: "1.1.0"
      date: "2026-02-15"
      changes:
        - "新增: 支持自定义超时"
```

### 5.3 工具组合（技能）

```yaml
# skills/data_processor/manifest.yaml
id: data_processor
name: 数据处理技能
version: 1.0.0
category: skill
description: 组合多个工具完成数据处理

# 定义工作流
workflow:
  steps:
    - name: fetch_data
      tool: http_request
      parameters:
        url: "${input.url}"
        method: GET

    - name: parse_data
      tool: json_parse
      parameters:
        data: "${steps.fetch_data.response}"

    - name: validate_data
      tool: schema_validate
      parameters:
        data: "${steps.parse_data.result}"
        schema: "${input.schema}"

    - name: transform_data
      tool: data_transform
      parameters:
        data: "${steps.validate_data.result}"
        rules: "${input.rules}"

    - name: save_result
      tool: file_write
      parameters:
        path: "${input.output_path}"
        content: "${steps.transform_data.result}"

# 输入定义
parameters:
  url:
    type: string
    description: 数据源 URL
    required: true
  schema:
    type: object
    description: 数据验证 schema
    required: true
  rules:
    type: object
    description: 转换规则
    required: true
  output_path:
    type: string
    description: 输出文件路径
    required: true
```

### 5.4 私有工具配置

```yaml
# 私有工具（不公开，仅自己可见）
id: my_private_tool
name: 私有工具
version: 1.0.0
category: tool
description: 仅我自己可见的工具

# 访问控制
access_control:
  visibility: private          # public | private | protected
  allowed_users:               # 允许访问的用户列表
    - alice
    - bob@example.com
  allowed_groups:              # 允许访问的组
    - team-alpha
    - org-beta

# 敏感配置（加密存储）
config:
  api_key: "${SECRET:my_api_key}"    # 从密钥管理服务读取
  webhook_url: "${SECRET:webhook_url}"
```

---

## 6. API 参考

### 6.1 工具查询

```bash
# 列出所有工具
GET /api/{namespace}/assets

# 按分类筛选
GET /api/{namespace}/assets?category=tool

# 按标签筛选
GET /api/{namespace}/assets?tags=weather,api

# 搜索工具
GET /api/{namespace}/assets?q=天气

# 获取工具详情
GET /api/{namespace}/assets/{asset_id}

# 获取工具的 YAML 源文件
GET /api/{namespace}/assets/{asset_id}/source
```

### 6.2 工具调用

```bash
# 调用工具
POST /api/{namespace}/assets/{asset_id}/invoke
{
  "parameters": {
    "city": "北京",
    "units": "celsius"
  },
  "options": {
    "timeout": 30,
    "retry": 3
  }
}

# 响应
{
  "success": true,
  "result": {
    "temperature": 22,
    "condition": "晴朗",
    "humidity": 45
  },
  "metadata": {
    "duration_ms": 1234,
    "cached": false,
    "version": "1.0.0"
  }
}
```

### 6.3 Webhook 事件

```bash
# GitHub Push 事件触发同步
POST /webhook/github/{namespace}
Headers:
  X-GitHub-Event: push
  X-Hub-Signature-256: sha256=...
  X-GitHub-Delivery: 12345-67890

Body:
{
  "ref": "refs/heads/main",
  "repository": {
    "name": "agent-tools",
    "owner": {"login": "alice"}
  },
  "pusher": {"name": "Alice"},
  "commits": [...]
}

# 响应
{
  "status": "triggered",
  "namespace": "user_alice",
  "branch": "main",
  "commit_sha": "abc123..."
}
```

---

## 7. 故障排查

### 7.1 常见问题

| 问题 | 可能原因 | 解决方案 |
|------|----------|----------|
| 工具未上线 | Webhook 未配置 | 检查 GitHub Webhook 设置 |
| 同步失败 | Token 过期 | 更新 Personal Access Token |
| 签名验证失败 | Secret 不匹配 | 检查 Webhook Secret 配置 |
| 404 错误 | 租户不存在 | 联系管理员确认租户配置 |
| 参数验证失败 | manifest 格式错误 | 使用 YAML 验证器检查 |

### 7.2 调试命令

```bash
# 查看租户状态
python main.py tenants

# 手动触发同步
python main.py sync --tenant your_namespace --verbose

# 查看工具详情
python main.py get tool_id --tenant your_namespace

# 健康检查
python main.py health

# 查看 Redis 数据
redis-cli
> KEYS asset:your_namespace:*
> HGETALL asset:your_namespace:metadata:tool_id
```

### 7.3 日志查看

```bash
# Webhook 服务器日志
tail -f /var/log/agent-assets/webhook.log

# 同步服务日志
tail -f /var/log/agent-assets/sync.log

# 错误日志
grep ERROR /var/log/agent-assets/*.log
```

---

## 8. FAQ

### Q1: 如何修改已发布的工具？

**A:** 直接修改 GitHub 仓库中的 `manifest.yaml`，然后 `git push`。Webhook 会自动触发同步更新。

### Q2: 能否删除已发布的工具？

**A:** 可以。在 GitHub 仓库中删除对应的目录，然后 `git push`。系统会自动清理 Redis 中的数据。

### Q3: 工具数据会丢失吗？

**A:** 不会。GitHub 是**唯一真实来源**，Redis 只是缓存。即使 Redis 数据丢失，重新同步即可恢复。

### Q4: 如何回滚到旧版本？

**A:** 使用 Git 回滚：

```bash
# 查看历史
git log --oneline

# 回滚到指定版本
git revert abc123

# 推送
git push origin main
```

### Q5: 可以在一个仓库中放多个工具吗？

**A:** 可以。在 `tools/` 目录下创建多个子目录，每个子目录包含一个 `manifest.yaml`。

### Q6: 如何共享工具给其他人？

**A:** 有三种方式：

1. **公开仓库**: 将 GitHub 仓库设为 Public
2. **组织租户**: 创建 `org_xxx` 类型的租户，邀请成员
3. **复制工具**: 让其他人 fork 你的仓库，然后接入系统

### Q7: 支持哪些 Git 平台？

**A:** 目前支持：
- GitHub (推荐)
- Gitee (计划中)
- GitLab (计划中)

---

## 附录

### A. manifest.yaml 快速模板

```yaml
id: my_tool
name: 我的工具
version: 1.0.0
category: tool
description: 工具描述

author: Your Name
tags: [tag1, tag2]

parameters:
  input:
    type: string
    required: true

examples:
  - input: {input: "test"}
    output: {result: "ok"}
```

### B. Git 常用命令

```bash
# 克隆仓库
git clone https://github.com/username/repo.git

# 创建分支
git checkout -b feature/new-tool

# 添加文件
git add tools/new_tool/manifest.yaml

# 提交
git commit -m "feat: 添加新工具"

# 推送
git push origin feature/new-tool

# 合并到主分支
git checkout main
git merge feature/new-tool
git push origin main
```

### C. 联系支持

- **文档**: https://docs.example.com
- **Issues**: https://github.com/example/issues
- **Email**: support@example.com
- **Discord**: https://discord.gg/example

---

*本文档持续更新中...*

*最后更新: 2026-03-04*
