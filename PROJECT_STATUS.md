
# AutoSeek 项目现状文档

> 更新时间: 2025-03-02
> 项目地址: https://e.coding.net/autoseek/autoseek/web-project

## 项目概述

AutoSeek 是一个**多 Agent 模拟平台**，支持动态创建和管理 Agent/Environment 实体，通过 Redis Streams 实现实时通信。

**技术栈:**
- **后端**: Go (Gin框架)
- **前端**: React + TypeScript + Vite
- **存储**: Redis (Cluster 支持，Hash-tag 策略)
- **认证**: Supabase
- **通信**: WebSocket + Redis Streams

---

## 后端架构

### 核心模块

| 模块 | 路径 | 功能 |
|------|------|------|
| WebSocket Gateway | `internal/core/websocket/` | 实时消息推送、项目状态同步 |
| Stream Manager | `internal/core/stream/` | Redis Streams 操作 (XADD/XREAD) |
| Store Layer | `internal/core/store/` | Redis 数据持久化 |
| Handlers | `internal/core/handlers/` | HTTP API 处理 |

### API 端点

#### 实体管理
```
POST   /api/v1/projects/:id/entities                    # 创建实体
GET    /api/v1/projects/:id/entities                    # 列出实体
GET    /api/v1/projects/:id/entities/:entity_id         # 获取实体详情
PUT    /api/v1/projects/:id/entities/:entity_id         # 更新实体
DELETE /api/v1/projects/:id/entities/:entity_id         # 删除实体
POST   /api/v1/projects/:id/entities/:entity_id/start   # 启动实体
POST   /api/v1/projects/:id/entities/:entity_id/stop    # 停止实体
```

#### 自定义属性 (新增)
```
GET    /api/v1/projects/:id/entities/:entity_id/properties           # 获取属性列表
PUT    /api/v1/projects/:id/entities/:entity_id/properties           # 批量更新属性值
PUT    /api/v1/projects/:id/entities/:entity_id/properties/:property/value      # 更新单个属性值
PUT    /api/v1/projects/:id/entities/:entity_id/properties/:property/definition  # 更新属性描述
DELETE /api/v1/projects/:id/entities/:entity_id/properties/:property          # 删除属性
```

#### LLM 配置 (新增)
```
GET    /api/v1/llm/providers         # 获取所有 LLM 提供商配置
GET    /api/v1/llm/config           # 获取完整 LLM 配置
```

#### 实体日志
```
GET    /api/v1/projects/:id/entities/:entity_id/logs        # 获取实时日志
GET    /api/v1/projects/:id/entities/:entity_id/logs/history  # 获取历史日志
```

---

## Redis 数据模型

### Key 命名规范 (Hash-tag 策略)

所有 Key 使用 Hash tag `{p:pid}` 或 `{u:uid}` 确保 Cluster 兼容性。

```
proj:{p:pid}:metadata                    # 项目元数据
idx:{p:pid}:root                        # 根实体 ID
ent:{p:pid}:e:{eid}:meta                # 实体元数据
ent:{p:pid}:e:{eid}:state               # 实体状态
ent:{p:pid}:e:{eid}:attr                # 实体自定义属性 (新增)
stream:{p:pid}:inbox:{eid}              # 实体消息箱
stream:{p:pid}:cmd                      # 项目命令流
ws:conn:{p:pid}:u:{uid}                # WebSocket 连接
```

### 自定义属性存储格式

**Key**: `ent:{p:pid}:e:{eid}:attr` (Hash)

```
HSET ent:{p:pid}:e:{eid}:attr
  level:v        "5"           # 属性值
  level:d        "等级"         # 属性描述
  skill_points:v "100"
  skill_points:d "技能点数"
```

**命名规则**:
- `{property_name}:v` - 属性值
- `{property_name}:d` - 属性描述

---

## 前端架构

### 组件结构

```
frontend/
├── components/
│   ├── EntityForm.tsx              # 实体创建表单
│   ├── EntityDetail.tsx            # 实体详情/配置页
│   ├── CreateEntityModal.tsx       # 创建弹窗
│   └── entity/form/
│       ├── PromptTemplateEditor.tsx  # 提示词编辑器
│       ├── ParentEntitySelector.tsx  # 父级选择器
│       ├── ToolPackageSelector.tsx   # 工具包选择器
│       └── KVEditor.tsx              # 键值对编辑器
└── src/
    ├── components/
    │   ├── entity/form/
    │   │   ├── PropertyEditor.tsx      # 属性编辑器 (新增)
    │   │   └── PropertyEditor.css
    │   └── layout/
    │       ├── WorldOutliner.tsx       # God Mode 实体列表
    │       ├── InspectorPanel.tsx      # 实体配置面板
    │       ├── TimeControlBar.tsx      # 时间控制条
    │       └── MarketplaceDock.tsx     # 资产库
    └── services/
        └── llmConfigService.ts         # LLM 配置服务 (新增)
```

### 核心功能

#### 1. Agent 创建表单

**位置**: `components/EntityForm.tsx`

**支持的字段**:
- 基本信息: 名称、描述、类型
- 系统提示词: 富文本编辑器
- 父级选择: 树形选择器
- LLM 配置: 8 个提供商，30+ 模型
- API Key: 用户保存的密钥管理
- Bifrost: 网关模式支持
- 工具包: public/file_tools/system_utils/dynamic
- **自定义属性**: 动态添加属性 (新增)

#### 2. 自定义属性编辑器

**位置**: `src/components/entity/form/PropertyEditor.tsx`

**功能**:
- 添加/删除属性
- 编辑: 属性名、描述、默认值
- 支持 Agent 创建时定义属性
- 支持 Agent 配置页编辑运行时值

#### 3. 资产库 (MarketSelector)

**位置**: `components/entity/form/MarketSelector.tsx`

**预定义内容**:

| 类型 | 数量 | 示例 |
|------|------|------|
| Laws (规则) | 6 | CombatLaw, LevelUpLaw, DeathLaw, PriorityRule... |
| Actions (动作) | 6 | SpawnMonster, WorldEvent, TradeShop, create_ticket... |

**分类**: 战斗、成长、队伍、业务、世界、经济

#### 4. LLM 配置服务

**位置**: `src/services/llmConfigService.ts`

**支持的提供商**:
1. DeepSeek - deepseek-chat, deepseek-coder, deepseek-reasoner
2. BigModel (智谱) - GLM-5, GLM-4 Plus, GLM-4 Flash...
3. OpenAI - GPT-4o, GPT-4o-mini, o1, o1-mini
4. Anthropic - Claude Sonnet 4, Claude 3 Opus/Haiku
5. Google (Gemini) - Gemini 2.5 Pro, Gemini 2.0 Flash
6. Qwen (通义千问) - Qwen Max, Qwen Turbo, Qwen Coder
7. Kimi (月之暗面) - Moonshot V1, Kimi K2.5
8. MiniMax - ABAB 6.5s/g/t, Speech Turbo

**配置来源**: 后端 API `/api/v1/llm/providers` (支持 ETag 缓存)

#### 5. God Mode (WorldOutliner)

**位置**: `src/components/layout/WorldOutliner.tsx`

**功能**:
- 显示环境/Agent 树形列表
- 实体状态实时同步
- 点击选中实体
- 添加新实体
- 刷新列表

**暂不支持**: 删除实体功能 (待添加)

---

## WebSocket 消息协议

### 客户端 → 服务器

```typescript
// 订阅消息
{ type: "subscribe", project_id: "...", user_id: "..." }

// 发送消息
{ type: "message", sender_id: "...", content: "...", target_id: "..." }
```

### 服务器 → 客户端

```typescript
// 订阅成功
{ type: "subscribed", project_id: "...", user_id: "..." }

// 收到消息
{ type: "message", sender_id: "...", content: "...", timestamp: ... }

// 项目状态更新
{ type: "project_status", status: "running" | "stopped" | ... }

// 实体删除通知 (新增)
{ type: "entity_deleted", entity_id: "..." }

// 错误
{ type: "error", error: "..." }
```

---

## 实体类型系统

### Agent (智能体)

```typescript
{
  entity_id: "agt_xxxxx",
  type: "agent",
  name: "客服专员 Alice",
  prompt_template: "你是专业的客服...",
  tool_package_set: ["public", "file_tools"],
  llm_provider: "deepseek",
  llm_model_name: "deepseek-chat",
  parent_id: "env_root",
  properties: [                    // 自定义属性 (新增)
    { name: "level", description: "等级", value: "5" }
  ]
}
```

### Environment (环境)

```typescript
{
  entity_id: "env_xxxxx",
  type: "env",
  name: "客服工作台",
  prompt_template: "环境规则...",
  laws: ["PriorityRule", "CombatLaw"],  // 环境规则
  actions: ["create_ticket"],           // 环境动作
  parent_id: ""  // 环境通常作为根节点
}
```

---

## 已知问题

### 1. 组件目录结构不统一

- **问题**: 存在两套组件目录
  - `frontend/components/` - 旧位置
  - `frontend/src/components/` - 新位置

- **影响**: PropertyEditor 在新位置，EntityForm 在旧位置，导入路径复杂

- **建议**: 统一迁移到 `src/` 目录结构

### 2. WorldOutliner 缺少删除功能

- **状态**: 实体列表没有删除按钮
- **影响**: 只能通过 API 或其他方式删除实体
- **解决方案**:
  1. 添加删除按钮 (悬停显示)
  2. 使用 WebSocket 实时通知删除

### 3. 属性功能测试不充分

- **状态**: 后端 API 和前端组件都已实现
- **问题**: 创建 Agent 时属性可能未正确写入 Redis
- **建议**: 端到端测试创建流程

---

## 配置文件

### config.yaml

```yaml
server:
  port: 8080
  host: "0.0.0.0"

redis:
  host: "localhost"
  port: 6379
  password: ""
  db: 0

supabase:
  url: "https://xxx.supabase.co"
  key: "anon_key"
  service_key: "service_role_key"
  jwt_secret: "JWT_secret"

websocket:
  read_buffer_size: 1024
  write_buffer_size: 1024
  max_message_size: 512000
  pong_wait: 60
  ping_period: 54

# LLM 提供商配置 (新增)
llm:
  providers:
    - id: deepseek
      name: DeepSeek
      api_base: https://api.deepseek.com
      models: [...]
    - id: bigmodel
      name: BigModel
      api_base: https://open.bigmodel.cn
      models: [...]
```

---

## 启动方式

### 开发环境

```bash
# 方式1: 使用管理脚本
./web_manager.sh start    # 启动所有服务
./web_manager.sh stop     # 停止所有服务
./web_manager.sh restart  # 重启
./web_manager.sh logs     # 查看日志

# 方式2: 手动启动
# 后端
go run cmd/api/main.go

# 前端
cd frontend
npm install
npm run dev
```

### 生产构建

```bash
# 后端
go build -o api-server cmd/api/main.go

# 前端
cd frontend
npm run build
```

---

## 默认端口

| 服务 | 端口 |
|------|------|
| 后端 API | 8080 |
| 前端 Dev Server | 3000 |
| Redis | 6379 |
| WebSocket (后端) | 8080/ws |

---

## 下一步计划

1. **统一组件目录结构** - 迁移到 `src/` 结构
2. **添加删除功能** - WorldOutliner 悬停删除按钮
3. **完善属性功能** - 端到端测试
4. **文档完善** - API 文档、组件文档
5. **测试覆盖** - 单元测试、集成测试

---

## 联系方式

- 项目地址: https://e.coding.net/autoseek/autoseek/web-project
- 问题反馈: 项目 Issues
- 技术文档: `/docs` 目录
