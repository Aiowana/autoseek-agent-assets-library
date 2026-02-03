这份设计文档是基于你提供的 `TECHNICAL_GUIDE.md` 进行的**架构升级版 (v1.1)**。它专门针对“减重”（性能优化）和“一致性”进行了增强。

你可以直接将此文档发给 Claude，作为它的**开发迭代任务书**。

---

# Agent 资产库同步服务升级提案 (v1.1) - 减重与一致性强化

## 1. 升级背景
在 v1.0 架构中，随着资产数量增加（如超过 100+ 个工具），前端一次性拉取所有详细元数据会导致性能下降。同时，双向同步（GitHub ↔ Redis）在并发场景下存在数据覆盖风险。本设计旨在通过“二级索引”与“乐观锁机制”解决上述问题。

---

## 2. 优化策略一：减重（二级数据结构）

### 2.1 现状与痛点
*   **现状**：前端调用接口时，系统从 Redis 返回所有资产的完整 `manifest.yaml` 解析内容。
*   **痛点**：数据量大，解析慢，消耗带宽。

### 2.2 解决方案：全局轻量索引 (Global Index)
在 Redis 中引入一个新的数据结构，专门用于列表展示。

**新 Redis 结构：**
```
Key: asset:index
Type: Hash
Fields:
  ├─ {asset_id_1}: "{'name': '...', 'category': '...', 'version': '...', 'icon': '...'}"
  ├─ {asset_id_2}: "{'name': '...', 'category': '...', 'version': '...', 'icon': '...'}"
```

**逻辑逻辑：**
- **同步服务**：在同步每个资产时，提取 `name`, `category`, `version` 等关键字段，组成一个极简 JSON，存入 `asset:index`。
- **前端请求**：
    1.  **列表页**：仅请求 `asset:index`。数据量减少 90%。
    2.  **详情页**：当用户点击具体资产时，再根据 ID 请求 `asset:metadata:{id}` 获取完整配置。

---

## 3. 优化策略二：一致性（增量同步与乐观锁）

### 3.1 增量同步逻辑 (SHA 追踪)
避免每次轮询都全量扫描 GitHub。

**操作流程：**
1.  **记录状态**：在 Redis `asset:sync:state` 中增加字段 `last_commit_sha`。
2.  **前置检查**：同步开始前，调用 GitHub API 获取当前分支最新的 `Commit SHA`。
3.  **比对**：
    - 如果 `current_sha == last_commit_sha`，说明仓库无任何变动，直接结束同步。
    - 如果不同，仅拉取发生变更的文件（使用 GitHub `/compare` 接口）或执行全量扫描后更新 SHA。

### 3.2 写入一致性：乐观锁 (Optimistic Locking)
防止 UI 端的修改覆盖了 GitHub 端刚发生的更新。

**操作流程：**
1.  **读取阶段**：前端加载资产时，必须同时获取该文件在 GitHub 的 `sha` 值。
2.  **修改阶段**：用户提交修改。
3.  **写入阶段**：
    - 调用 `github_manager.save_to_github()` 时，必须传入获取到的 `old_sha`。
    - GitHub API 会自动比对。如果 `old_sha` 与服务器当前 SHA 不一致（说明有人捷足先登改了代码），API 会报错。
    - **报错处理**：系统提示用户：“资产已被他人更新，请刷新后重试”。

---

## 4. 改进后的数据结构定义

### 4.1 Redis 存储结构更新

| Key | 类型 | 描述 |
| :--- | :--- | :--- |
| **`asset:index`** | **Hash** | **[新增]** 极简索引。Field: ID, Value: 摘要 JSON |
| `asset:metadata:{id}` | Hash | 详情。增加字段 `github_sha` 存储文件哈希 |
| `asset:sync:state` | Hash | 状态。增加字段 `last_commit_sha` 记录上次同步节点 |

---

## 5. 组件修改指南 (面向 Claude 的开发任务)

### 5.1 修改 `RedisClient`
- **任务**：实现 `update_index(asset_data)` 方法。在 `save_asset_atomic` 的 pipeline 中同步更新 `asset:index`。
- **任务**：实现 `get_index()` 方法，供后端 API 调用，返回所有资产的轻量级列表。

### 5.2 修改 `GitHubManager`
- **任务**：在 `save_to_github` 方法中增加 `sha` 参数支持。
- **任务**：封装 `check_repo_update()` 方法，通过对比 `last_commit_sha` 决定是否需要执行同步。

### 5.3 修改 `AssetSyncService`
- **任务**：重写 `sync_from_github` 逻辑。
    1. 获取最新 Commit SHA 并比对。
    2. 执行扫描。
    3. 同步完成后，原子性地更新元数据、索引和新的 `last_commit_sha`。
- **任务**：增加 `cleanup_orphans()` 逻辑。如果 Redis 索引中有的 ID 在 GitHub 中再也找不到了（被删除了），则从索引和元数据中同步清除。

---

## 6. 给 Claude 的具体 Prompt 示例

> “你好 Claude，基于现有的 `TECHNICAL_GUIDE.md`，请执行以下架构升级：
> 1. **实现‘减重’方案**：在 Redis 中引入 `asset:index` 结构，存储资产的摘要信息（ID, Name, Category, Version），并在同步时自动维护该索引。
> 2. **实现增量同步检测**：通过追踪 GitHub 分支的最新 `Commit SHA` 来避免无效的重复扫描。
> 3. **实现写入一致性**：在 `save_to_github` 方法中引入 GitHub 文件 SHA 校验，确保用户在 Web UI 上的修改不会发生覆盖冲突。
> 4. **清理逻辑**：确保当 GitHub 端的文件夹被彻底删除时，Redis 中的索引和元数据能被同步移除。
> 请先从 Redis 索引维护和 Commit SHA 校验的逻辑开始实现。”

---

### 评价建议：
这份文档通过 **`asset:index`** 解决了前端的性能负担（减重），通过 **`last_commit_sha`** 和 **`github_sha`** 解决了数据同步和并发冲突的隐患（一致性）。

**你现在就可以把这个“架构升级手册”发给 Claude 了。** 这样它写出来的代码不仅能跑通，而且具备了处理真实复杂业务的能力。