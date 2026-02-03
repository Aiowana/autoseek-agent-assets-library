# Redis Key 命名规范 v1.1

> 本文档定义 Agent 资产库系统在 Redis/Tendis 中的数据存储规范。所有组件必须严格遵循此约定。

---

## 1. 命名空间约定

所有 Key 使用 `:` 分隔，采用以下命名空间前缀：

| 前缀 | 用途 |
|------|------|
| `asset:` | 资产相关数据 |
| `project:` | 项目相关数据（预留） |
| `task:` | 任务队列相关数据（预留） |

---

## 2. 资产元数据存储

### 2.1 单个资产元数据

```
Key:    asset:metadata:{id}
Type:   Hash
TTL:    永久
```

**字段定义：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 资产唯一标识符，与 Key 中的 {id} 一致 |
| `version` | string | 语义化版本号 (semver)，如 "1.0.0" |
| `category` | string | 资产类别：`tool` \| `prompt` \| `skill` |
| `name` | string | 前端展示名称 |
| `description` | string | 资产功能描述 |
| `config_schema` | json | `config_schema` 的 JSON 序列化字符串 |
| `agent_specs` | json | `agent_specs` 的 JSON 序列化字符串 |
| `runtime` | json | `runtime` 的 JSON 序列化字符串 |
| `github_path` | string | GitHub 仓库中的相对路径，如 `tools/search/google.yaml` |
| `github_sha` | string | GitHub 文件的 SHA-1 值，用于变更检测 |
| `created_at` | timestamp | 资产创建时间（Unix timestamp） |
| `updated_at` | timestamp | 资产最后更新时间（Unix timestamp） |

**示例：**
```redis
HSET asset:metadata:google_search \
  id "google_search" \
  version "1.2.0" \
  category "tool" \
  name "Google 搜索" \
  description "在 Google 上搜索内容" \
  config_schema "[{\"name\":\"query\",\"label\":\"搜索词\",\"type\":\"string\",\"required\":true}]" \
  agent_specs "{\"function_name\":\"google_search\",\"description\":\"...\",\"parameters\":{...}}" \
  runtime "{\"language\":\"python\",\"entry\":\"main.py\",\"handler\":\"run\",\"dependencies\":[\"requests\"]}" \
  github_path "tools/search/google.yaml" \
  github_sha "abc123def456..." \
  created_at "1704067200" \
  updated_at "1704153600"
```

---

## 3. 分类索引

### 3.1 按类别索引

```
Key:    asset:category:{category}
Type:   Set
TTL:    永久
```

**说明：** 存储指定类别下的所有资产 ID

**示例：**
```redis
SADD asset:category:tool google_search bing_search weather_api
SADD asset:category:prompt summarizer translator code_reviewer
SADD asset:category:skill data_analysis report_generation
```

**查询：** 获取所有工具类资产
```redis
SMEMBERS asset:category:tool
```

---

## 4. 全局轻量索引

### 4.1 全局索引

```
Key:    asset:index
Type:   Hash
TTL:    永久
```

**说明：** 存储所有资产的轻量级摘要，用于前端快速列表展示

**字段定义：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 资产 ID |
| `name` | string | 资产名称 |
| `category` | string | 资产类别 |
| `version` | string | 版本号 |
| `description` | string | 资产描述（截取前 100 字符） |

**示例：**
```redis
HSET asset:index \
  http_search '{"id":"http_search","name":"HTTP 请求工具","category":"tool","version":"1.0.0","description":"发送 HTTP GET/POST 请求"}' \
  text_summarizer '{"id":"text_summarizer","name":"文本总结","category":"prompt","version":"1.0.0","description":"将长文本总结为简洁的摘要"}'
```

**查询：** 获取所有资产摘要
```redis
HGETALL asset:index
```

**用途：**
- 前端列表页一次请求获取所有资产摘要（数据量减少 90%）
- 详情页按需请求 `asset:metadata:{id}` 获取完整配置

---

## 5. 同步状态管理

### 5.1 全局同步状态

```
Key:    asset:sync:state
Type:   Hash
TTL:    永久
```

**字段定义：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `last_sync_time` | timestamp | 上次完整同步的时间戳 |
| `last_commit_sha` | string | 上次同步时 GitHub 分支的最新 commit SHA |
| `synced_count` | int | 已同步的资产总数 |
| `sync_status` | string | 同步状态：`idle` \| `syncing` \| `failed` |

**示例：**
```redis
HSET asset:sync:state \
  last_sync_time "1704153600" \
  last_commit_sha "abc123def456..." \
  synced_count "42" \
  sync_status "idle"
```

**last_commit_sha 的用途：**
- 增量同步检测：对比当前 commit SHA，如未变化则跳过同步
- 避免无效扫描：减少 GitHub API 调用

### 5.2 变更记录队列

```
Key:    asset:sync:changed
Type:   List
TTL:    永久
```

**说明：** 记录每次同步时发生变更的资产 ID，按时间顺序排列

**操作：**
```redis
# 同步时追加变更的资产 ID
RPUSH asset:sync:changed google_search weather_api

# 获取最近 N 次变更
LRANGE asset:sync:changed -10 -1

# 可选：定期清理旧记录，保留最近 1000 条
LTRIM asset:sync:changed -1000 -1
```

---

## 5. 操作约定

### 5.1 原子性操作

写入资产时，应使用 Redis 事务保证一致性：

```redis
MULTI
HSET asset:metadata:{id} ...
SADD asset:category:{category} {id}
EXEC
```

### 5.2 版本控制策略

同步时仅当 `github_sha` 发生变化时才更新元数据：

```python
current_sha = redis.hget(f"asset:metadata:{asset_id}", "github_sha")
if current_sha != new_github_sha:
    # 执行更新
    pass
```

### 5.3 增量同步

利用 `last_sync_time` 和 GitHub API 的 `since` 参数实现增量同步：

```python
since = redis.hget("asset:sync:state", "last_sync_time")
commits = github.get_commits(since=since)
```

---

## 6. 预留扩展

### 6.1 搜索索引（未实现）

```
Key:    asset:search:index
Type:   RedisSearch Index (或自行实现前缀树)
```

### 6.2 项目配置（预留）

```
Key:    project:config:{project_id}
Type:   Hash
```

### 6.3 任务队列（预留）

```
Key:    task:queue:pending
Type:   List

Key:    task:status:{task_id}
Type:   Hash
```

---

## 7. 版本历史

| 版本 | 日期 | 变更说明 |
|------|------|----------|
| v1.1 | 2024-02-03 | 添加 `asset:index` 全局轻量索引；`last_sync_sha` 更名为 `last_commit_sha` |
| v1.0 | 2024-01-01 | 初始版本 |

---

**所有代码实现必须严格遵循本规范。规范变更需经评审后更新版本号。**
