为了回应你关于“一个工具一个 YAML 太重”以及“数据一致性”的担忧，这份修改文档专门针对**架构优化**和**同步机制**进行了升级。

你可以直接将此文档发给 Claude，它会引导 Claude 从“简单同步”转向“高性能、高一致性”的系统设计。

---

# 架构优化与一致性方案修改手册 (v1.1)

## 1. 核心问题对策：解决“资产太重”
为了避免前端频繁读取大量零散的 YAML 文件，我们将引入 **“二级数据结构”** 策略：
*   **物理层 (GitHub)**：保持“一工具一文件夹一 YAML”的原子性。这有利于分布式开发、版本控制和按需加载。
*   **视图层 (Redis Index)**：同步服务在处理完零散 YAML 后，在 Redis 中自动生成一个**全局索引 (Global Index)**。前端只需请求一次索引，即可获得所有资产的摘要（如 ID、名称、图标）。

## 2. 一致性保障协议 (Consistency Protocol)
为了确保 GitHub (事实来源) 与 Redis (运行缓存) 之间的数据同步，系统需遵循以下逻辑：

### 2.1 增量同步机制 (Delta Sync)
*   **Commit SHA 追踪**：Redis 中存储 `assets:sync:last_commit`。
*   **逻辑**：同步前先获取 GitHub 仓库的最新的 Commit SHA。
    *   如果 SHA 未变，直接跳过扫描（极速）。
    *   如果 SHA 发生变化，通过 GitHub API 获取差异文件 (Diff)，仅更新变动的文件夹。

### 2.2 双向写入的一致性 (Write-Back Logic)
当用户在 Web UI 修改配置并保存时，采取“两阶段提交”逻辑：
1.  **锁定与写回**：后端调用 GitHub API 提交更新。
2.  **异步确权**：GitHub 返回成功（包含新的 Commit SHA）后，后端更新 Redis 中的数据并更新 `last_commit` 标记。
3.  **防冲突**：使用 GitHub API 的 `SHA` 校验功能，确保在写入时文件未被他人修改（类似乐观锁）。

---

## 3. Redis 数据结构优化建议
请 Claude 在编写代码时采用以下存储设计：

*   **`asset:index` (Hash)**: 存储所有资产的简要信息。
    *   `Field`: `asset_id`
    *   `Value`: `{ "name": "...", "category": "...", "version": "..." }` (JSON 字符串)
*   **`asset:metadata:{id}` (String)**: 存储该资产完整的 YAML 解析内容。
*   **`asset:sync:status` (Hash)**:
    *   `last_commit`: 最近一次同步的 GitHub Commit SHA。
    *   `last_sync_time`: 时间戳。

---

## 4. 给 Claude 的具体修改指令

**“你好 Claude，针对之前的资产库设计，我们需要在同步逻辑和一致性上进行深度优化，请按以下要求修改代码实现：”**

1.  **实现增量同步**：
    - 请在 `GitHubManager` 中增加检测 Commit SHA 的功能。
    - 仅在 GitHub 有新提交时才触发扫描。
2.  **建立全局索引**：
    - 在同步过程中，除了存储单个资产的详细元数据，请自动维护一个名为 `asset:index` 的 Redis Hash，供前端快速拉取列表。
3.  **强化反向写入**：
    - 在执行 `save_to_github` 时，必须包含对 GitHub 文件原始 SHA 的校验，防止并发覆盖。
    - 写入成功后，立即更新 Redis 中的本地缓存，确保前端看到的是最新状态。
4.  **一致性校验脚本**：
    - 提供一个辅助函数 `check_integrity()`，通过对比 Redis 索引和 GitHub 文件树，发现并修复潜在的孤儿数据（即 GitHub 已删但 Redis 还留存的数据）。

---

### Claude 收到此文档后将明白：
*   他需要写的不是一个简单的“拷贝”程序，而是一个具备**状态感知**能力的同步引擎。
*   系统必须通过 **Global Index** 解决“文件太碎”导致的性能问题。
*   **数据一致性**是架构的生命线，必须通过 Commit SHA 和乐观锁来捍卫。

**你现在可以把这份修改手册发给 Claude，让他开始重构同步服务的代码逻辑了。**