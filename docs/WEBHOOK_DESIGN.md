# Webhook 支持技术设计文档

## 1. 概述

### 1.1 背景

当前系统采用轮询（Polling）模式同步 GitHub 仓库变更，存在以下问题：
- 实时性差：默认 300 秒轮询间隔，变更感知延迟高
- 资源浪费：无变更时仍持续发起 API 请求
- 配额消耗：每次轮询都消耗 GitHub API 调用次数

### 1.2 目标

引入 Webhook 机制，实现：
- **实时同步**：GitHub 主动推送变更事件，延迟 < 5 秒
- **资源优化**：按需触发，消除无效轮询
- **双模式支持**：保留轮询作为降级方案

### 1.3 范围

本文档描述 Webhook 服务的设计与实现，包括：
- HTTP 服务器架构
- Webhook 事件接收与处理
- 安全签名验证机制
- 与现有同步服务的集成

---

## 2. 架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         GitHub Repository                        │
│                     (push / pull request / etc.)                 │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             │ HTTP POST (Webhook Event)
                             │ X-Hub-Signature-256: sha256=...
                             │ X-GitHub-Event: push
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Webhook Server (FastAPI)                     │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                   /webhook/github                         │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │  1. Signature Validation (HMAC-SHA256)              │  │  │
│  │  │  2. Event Type Routing                              │  │  │
│  │  │  3. Branch Filtering                                │  │  │
│  │  │  4. Async Sync Trigger                              │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             │ trigger_sync()
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      AssetSyncService                            │
│                   (existing sync logic)                          │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  • incremental_sync()                                      │  │
│  │  • sync_from_github()                                      │  │
│  │  • Redis update                                            │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 模块结构

```
sync_service/
├── webhook/                    # 新增 Webhook 模块
│   ├── __init__.py
│   ├── server.py               # FastAPI 应用入口
│   ├── handler.py              # Webhook 事件处理器
│   ├── verifier.py             # 签名验证器
│   └── models.py               # Webhook 数据模型
├── sync_service.py             # 现有同步服务
├── redis_client.py             # Redis 客户端
└── ...
```

### 2.3 运行模式

系统支持三种运行模式：

| 模式 | 启动命令 | 说明 |
|------|----------|------|
| CLI 模式 | `python main.py sync` | 一次性同步 |
| 轮询模式 | `python main.py sync --continuous` | 定时轮询同步 |
| Webhook 模式 | `python main.py serve` | HTTP 服务器 + Webhook |

---

## 3. API 接口设计

### 3.1 Webhook 接收端点

```
POST /webhook/github
```

#### 请求头

| Header | 说明 | 示例 |
|--------|------|------|
| `X-GitHub-Event` | 事件类型 | `push`, `ping`, `release` |
| `X-Hub-Signature-256` | HMAC 签名 | `sha256=abc123...` |
| `X-GitHub-Delivery` | 唯一交付 ID | `123e4567-e89b-12d3` |
| `Content-Type` | 内容类型 | `application/json` |

#### 请求体（push 事件示例）

```json
{
  "ref": "refs/heads/main",
  "repository": {
    "name": "autoseek-agent-assets-library",
    "full_name": "owner/repo",
    "default_branch": "main"
  },
  "pusher": {
    "name": "username",
    "email": "user@example.com"
  },
  "sender": {
    "login": "username",
    "type": "User"
  },
  "before": "a1b2c3d4...",
  "after": "e5f6g7h8...",
  "commits": [
    {
      "id": "commit_sha",
      "message": "Add new asset",
      "added": ["tools/new_asset/manifest.yaml"],
      "modified": [],
      "removed": []
    }
  ]
}
```

#### 响应

| 状态码 | 说明 |
|--------|------|
| `200` | Webhook 已接收，同步已触发 |
| `202` | 事件已忽略（非目标分支） |
| `403` | 签名验证失败 |
| `400` | 请求格式错误 |

### 3.2 健康检查端点

```
GET /health
```

响应：
```json
{
  "status": "healthy",
  "webhook": {
    "last_received": "2026-03-02T10:30:00Z",
    "total_received": 42,
    "last_sync_duration_ms": 1234
  },
  "services": {
    "redis": true,
    "github": true
  }
}
```

### 3.3 Webhook 状态查询

```
GET /webhook/status
```

响应：
```json
{
  "configured": true,
  "secret_set": true,
  "events_supported": ["push", "ping"],
  "target_branch": "main"
}
```

---

## 4. 安全机制

### 4.1 签名验证

GitHub 使用 HMAC-SHA256 对 Webhook 负载进行签名：

```python
def verify_signature(payload: bytes, received_signature: str, secret: str) -> bool:
    """
    验证 GitHub Webhook 签名

    Args:
        payload: 原始请求体（bytes）
        received_signature: X-Hub-Signature-256 请求头
        secret: 配置的 Webhook Secret

    Returns:
        bool: 签名是否有效
    """
    # 计算期望签名
    expected_signature = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()

    # 格式: sha256=<hex_string>
    expected = f"sha256={expected_signature}"

    # 使用常量时间比较防止时序攻击
    return hmac.compare_digest(expected, received_signature)
```

### 4.2 安全配置项

| 配置项 | 环境变量 | 说明 | 必需 |
|--------|----------|------|------|
| Webhook Secret | `GITHUB_WEBHOOK_SECRET` | 签名验证密钥 | 是 |
| Allowed IPs | `WEBHOOK_ALLOWED_IPS` | 限制 GitHub IP 范围 | 否 |
| Rate Limit | `WEBHOOK_RATE_LIMIT` | 每分钟最大请求数 | 否 |

### 4.3 GitHub IP 白名单

可选地验证请求来源 IP：

```python
GITHUB_WEBHOOK_IPS = [
    "192.30.252.0/22",
    "185.199.108.0/22",
    "140.82.112.0/20",
    # ... 更多 IP 段
]

def is_github_ip(ip: str) -> bool:
    """检查 IP 是否在 GitHub Webhook IP 范围内"""
    import ipaddress
    return any(
        ipaddress.ip_address(ip) in ipaddress.ip_network(cidr)
        for cidr in GITHUB_WEBHOOK_IPS
    )
```

---

## 5. 事件处理

### 5.1 支持的事件类型

| 事件 | 处理逻辑 |
|------|----------|
| `push` | 触发增量同步 |
| `ping` | 返回 pong，验证连接 |
| `release` | 可选：同步特定版本 |

### 5.2 处理流程

```python
async def handle_webhook(request: Request) -> JSONResponse:
    # 1. 验证签名
    payload = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    if not verify_signature(payload, signature):
        raise HTTPException(status_code=403)

    # 2. 解析事件
    event_type = request.headers.get("X-GitHub-Event")
    data = await request.json()

    # 3. 路由处理
    if event_type == "ping":
        return {"message": "pong"}

    if event_type == "push":
        # 检查分支
        ref = data.get("ref", "")
        target_branch = f"refs/heads/{config.github.branch}"
        if ref != target_branch:
            return {"status": "ignored", "reason": "branch_not_matched"}

        # 异步触发同步
        asyncio.create_task(trigger_sync())
        return {"status": "triggered"}

    return {"status": "ignored", "reason": "unsupported_event"}
```

### 5.3 同步触发策略

| 策略 | 说明 | 适用场景 |
|------|------|----------|
| 立即同步 | 收到 Webhook 后立即触发 | 默认 |
| 防抖延迟 | 多个事件合并，延迟 N 秒后触发 | 高频提交场景 |
| 排队执行 | 任务队列串行执行 | 避免并发冲突 |

---

## 6. 配置说明

### 6.1 新增环境变量

```bash
# .env
# ============================================
# Webhook Configuration
# ============================================
WEBHOOK_ENABLED=true                          # 是否启用 Webhook
WEBHOOK_HOST=0.0.0.0                          # 监听地址
WEBHOOK_PORT=8080                             # 监听端口
GITHUB_WEBHOOK_SECRET=your_secret_key_here    # Webhook 签名密钥

# 可选配置
WEBHOOK_WORKERS=4                             # Worker 进程数
WEBHOOK_LOG_LEVEL=INFO                        # 日志级别
WEBHOOK_TIMEOUT=30                            # 请求超时（秒）
```

### 6.2 配置文件更新

```yaml
# settings.yaml
webhook:
  enabled: true
  host: "0.0.0.0"
  port: 8080
  secret: ""                    # 从环境变量读取
  secret_ref: "GITHUB_WEBHOOK_SECRET"

  # 安全选项
  verify_ip: false              # 是否验证来源 IP
  allowed_ips: []               # IP 白名单

  # 性能选项
  workers: 4
  timeout: 30

  # 同步选项
  sync_on_push: true
  debounce_seconds: 0           # 防抖延迟（0 = 立即触发）
```

---

## 7. GitHub 配置

### 7.1 Webhook 设置步骤

1. 进入 GitHub 仓库设置
   ```
   Repository → Settings → Webhooks → Add webhook
   ```

2. 填写配置
   ```
   Payload URL: https://your-domain.com/webhook/github
   Content type: application/json
   Secret: [与 GITHUB_WEBHOOK_SECRET 一致]
   ```

3. 选择事件
   ```
   ✅ Just the push event
   或
   ✅ Send me everything
   ```

4. 保存后测试

### 7.2 Webhook 测试

GitHub 提供最近交付记录：

```
Webhooks → [your webhook] → Recent Deliveries
```

可查看：
- 请求/响应详情
- 触发事件
- 错误信息

---

## 8. 部署指南

### 8.1 本地开发

```bash
# 启动 Webhook 服务器
python main.py serve

# 或使用 uvicorn 直接启动
uvicorn sync_service.webhook.server:app --reload --port 8080
```

### 8.2 生产部署

#### 方案 A：直接部署

```bash
# 使用 gunicorn + uvicorn workers
gunicorn sync_service.webhook.server:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8080 \
  --access-logfile - \
  --error-logfile -
```

#### 方案 B：Docker 部署

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080
CMD ["python", "main.py", "serve"]
```

```yaml
# docker-compose.yml
services:
  webhook:
    build: .
    ports:
      - "8080:8080"
    environment:
      - WEBHOOK_ENABLED=true
      - GITHUB_WEBHOOK_SECRET=${SECRET}
      - REDIS_HOST=redis
    depends_on:
      - redis
```

#### 方案 C：反向代理

使用 Nginx/Caddy 作为前端：

```nginx
# nginx.conf
location /webhook/github {
    proxy_pass http://localhost:8080;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

### 8.3 暴露公网访问

开发环境可使用隧道工具：

```bash
# 使用 ngrok
ngrok http 8080

# 使用 cloudflare tunnel
cloudflared tunnel --url http://localhost:8080
```

---

## 9. 与现有系统集成

### 9.1 CLI 命令扩展

```bash
# 新增 serve 命令
python main.py serve [--host HOST] [--port PORT]

# 查看服务状态
python main.py status

# Webhook 测试命令
python main.py webhook --test
```

### 9.2 双模式兼容

```python
# main.py 新增命令
def cmd_serve(args, config: Config):
    """启动 Webhook 服务器"""
    from sync_service.webhook import create_app

    app = create_app(config)
    import uvicorn
    uvicorn.run(
        app,
        host=args.host or config.webhook.host,
        port=args.port or config.webhook.port,
        log_level="info"
    )
```

### 9.3 状态共享

Webhook 模式与轮询模式共享同一个 Redis 状态：

```
# Redis 状态键
asset:sync:last_trigger          # 最后触发方式 (webhook/poll)
asset:sync:webhook_count         # Webhook 触发次数
asset:sync:last_webhook          # 最后 Webhook 时间
```

---

## 10. 故障处理

### 10.1 常见问题

| 问题 | 可能原因 | 解决方案 |
|------|----------|----------|
| 签名验证失败 | Secret 不匹配 | 检查 GITHUB_WEBHOOK_SECRET 配置 |
| 收不到 Webhook | URL 不可达 | 检查防火墙/端口配置 |
| 同步未触发 | 分支不匹配 | 确认 target_branch 配置 |
| 重复同步 | 多次 Webhook | 启用防抖机制 |

### 10.2 日志监控

```python
# Webhook 专用日志
WEBHOOK_LOGGER = logging.getLogger("webhook")

# 记录关键事件
WEBHOOK_LOGGER.info(f"Webhook received: event={event_type}, delivery={delivery_id}")
WEBHOOK_LOGGER.info(f"Sync triggered: commit_sha={commit_sha}")
WEBHOOK_LOGGER.error(f"Signature verification failed: ip={client_ip}")
```

### 10.3 告警规则

可配置告警规则：
- 连续 N 次签名验证失败
- Webhook 交付失败率 > X%
- 同步执行时间 > Y 秒

---

## 11. 测试方案

### 11.1 单元测试

```python
# tests/test_webhook.py

def test_signature_verification():
    payload = b'{"test": "data"}'
    secret = "test_secret"

    # 生成签名
    signature = generate_signature(payload, secret)

    # 验证签名
    assert verify_signature(payload, signature, secret)

def test_event_parsing():
    event_data = load_fixture("push_event.json")

    handler = WebhookHandler()
    result = handler.parse_event(event_data)

    assert result.event_type == "push"
    assert result.branch == "main"
```

### 11.2 集成测试

```python
def test_webhook_to_sync_flow():
    # 模拟 Webhook 请求
    with TestClient(app) as client:
        response = client.post(
            "/webhook/github",
            json=push_event_payload,
            headers={"X-Hub-Signature-256": signature}
        )

    # 验证同步被触发
    assert response.status_code == 200
    # 验证 Redis 状态更新
```

### 11.3 本地测试

使用 `smee.io` 或 GitHub CLI 模拟 Webhook：

```bash
# 使用 gh cli 测试
gh webhook testing --event push --repo owner/repo

# 或使用 curl 手动测试
curl -X POST http://localhost:8080/webhook/github \
  -H "Content-Type: application/json" \
  -H "X-Hub-Signature-256: sha256=..." \
  -d @test_payload.json
```

---

## 12. 开发计划

### Phase 1: 核心 Webhook 服务器
- [ ] 创建 `sync_service/webhook/` 模块
- [ ] 实现 FastAPI 服务器
- [ ] 实现签名验证
- [ ] 实现事件路由

### Phase 2: 同步集成
- [ ] 集成到 `AssetSyncService`
- [ ] 实现异步触发逻辑
- [ ] 添加状态追踪

### Phase 3: 配置与部署
- [ ] 更新配置系统
- [ ] 添加 CLI 命令
- [ ] 编写部署文档

### Phase 4: 测试与监控
- [ ] 单元测试
- [ ] 集成测试
- [ ] 日志与监控

---

## 13. 附录

### 13.1 Webhook Payload 示例

详见：`docs/webhook_samples/` 目录
- `push.json` - Push 事件
- `ping.json` - Ping 事件
- `release.json` - Release 事件

### 13.2 参考资料

- [GitHub Webhooks 文档](https://docs.github.com/en/developers/webhooks-and-events/webhooks/about-webhooks)
- [Webhook 事件类型](https://docs.github.com/en/developers/webhooks-and-events/webhooks/webhook-events-and-payloads)
- [HMAC 签名验证](https://en.wikipedia.org/wiki/HMAC)

### 13.3 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-03-02 | 初始设计 |
