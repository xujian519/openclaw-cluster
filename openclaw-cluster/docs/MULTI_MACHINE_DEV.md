# OpenClaw 集群系统 - 多机开发指南

## 📋 概述

本指南适用于在多台设备上进行 OpenClaw 集群系统的开发和测试，帮助你高效地在不同机器间协同工作。

## 🏗️ 推荐的部署架构

```
┌─────────────────────────────────────────────────────────────┐
│                    开发环境架构                               │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   主机 A (Mac Pro)                    主机 B (MacBook)      │
│   ├─ 协调器 (Coordinator)             ├─ 工作节点 1         │
│   ├─ 工作节点 0                       ├─ 开发环境           │
│   ├─ Git 仓库                        ├─ Git 仓库克隆       │
│   └─ VSCode/IDE                      └─ VSCode/IDE         │
│                    │                                         │
│              ┌─────┴─────┐                                   │
│              │  Tailscale │                                   │
│              │   Mesh 网络 │                                   │
│              └───────────┘                                   │
│                    │                                         │
│   主机 C (Windows)                  主机 D (可选)            │
│   ├─ 工作节点 2                      ├─ 工作节点 N           │
│   └─ Git 仓库克隆                    └─ Git 仓库克隆         │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## 🚀 快速开始：在其他电脑上设置开发环境

### 步骤 1：克隆代码仓库

```bash
# 在每台新机器上执行
git clone <你的仓库地址> openclaw-cluster
cd openclaw-cluster
```

### 步骤 2：安装依赖

```bash
# macOS/Linux
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Windows
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 步骤 3：配置 Tailscale

```bash
# 安装 Tailscale（如果尚未安装）
# macOS
brew install --cask tailscale

# Windows
# 从 https://tailscale.com/download 下载安装

# 启动并登录
sudo tailscale up
```

### 步骤 4：获取 Tailscale IP

```bash
# 查看你的 Tailscale IP
tailscale ip -4

# 示例输出：
# 100.x.x.x
```

### 步骤 5：配置节点

创建配置文件 `config/config.yaml`：

```yaml
# 存储配置
storage:
  type: sqlite
  path: ./data/cluster.db

# 协调器配置（仅主机 A 需要）
coordinator:
  host: 0.0.0.0
  port: 8888
  heartbeat_timeout: 90
  heartbeat_check_interval: 30

# 工作节点配置（所有机器都需要）
worker:
  max_concurrent_tasks: 5
  heartbeat_interval: 5
  skills_dir: ./skills
  port: 18789

# 通信配置 - 重要！
communication:
  # 使用主机的 Tailscale IP
  nats_url: nats://100.x.x.x:4222

# 日志配置
log:
  level: INFO
  format: json
```

### 步骤 6：启动服务

```bash
# 在主机 A 上：启动协调器
python scripts/start_coordinator.py

# 在所有机器上：启动工作节点
python scripts/start_worker.py
```

## 🔄 开发工作流

### 场景 1：单机开发测试

```bash
# 在单台机器上测试协调器 + 工作节点
./scripts/quick_start.sh
```

### 场景 2：多机协同开发

**主机 A（主开发机）：**
```bash
# 启动协调器和本地工作节点
python scripts/start_coordinator.py &
python scripts/start_worker.py --node-id worker-main &
```

**主机 B：**
```bash
# 启动远程工作节点
python scripts/start_worker.py --node-id worker-macbook
```

**主机 C：**
```bash
# Windows 工作节点
python scripts/start_worker.py --node-id worker-windows
```

### 场景 3：分布式调试

在每台机器上查看日志：

```bash
# 实时查看协调器日志（主机 A）
tail -f logs/coordinator.log

# 实时查看工作节点日志（所有机器）
tail -f logs/worker.log
```

## 🛠️ 开发工具配置

### VSCode 远程开发

1. **安装 Remote SSH 扩展**
2. **配置 SSH 访问**

```bash
# ~/.ssh/config
Host macbook
    HostName 100.x.x.x  # Tailscale IP
    User xujian
    ForwardAgent yes
```

3. **在 VSCode 中打开远程文件夹**

### 使用 tmux/screen 保持会话

```bash
# 创建持久会话
tmux new -s coordinator
python scripts/start_coordinator.py

# 断开会话（保持运行）
Ctrl+B, D

# 重新连接
tmux attach -t coordinator
```

## 📦 代码同步策略

### 方案 1：Git + GitHub（推荐）

```bash
# 主机 A：开发后提交
git add .
git commit -m "feat: 添加新功能"
git push origin main

# 主机 B/C：拉取更新
git pull origin main
```

### 方案 2：rsync 快速同步

```bash
# 从主机 A 同步到主机 B
rsync -avz --exclude='venv' --exclude='*.pyc' --exclude='__pycache__' \
    --exclude='.git' --exclude='data' --exclude='logs' \
    /Users/xujian/openclaw/openclaw-cluster/ \
    xujian@100.x.x.x:~/openclaw-cluster/
```

### 方案 3：Syncthing 实时同步

1. 在所有机器上安装 Syncthing
2. 添加共享文件夹指向项目目录
3. 排除 `venv/`, `__pycache__/`, `data/`, `logs/`

## 🧪 测试流程

### 单元测试

```bash
# 在所有机器上运行
source venv/bin/activate
pytest tests/ -v
```

### 集成测试

```bash
# 主机 A：启动所有服务
./scripts/quick_start.sh

# 另一个终端：运行测试
pytest tests/integration/ -v
```

### 多节点测试

```bash
# 1. 在主机 A 启动协调器
python scripts/start_coordinator.py

# 2. 在主机 B、C 启动工作节点
python scripts/start_worker.py

# 3. 在主机 A 运行多节点测试
pytest tests/test_multi_node.py -v
```

## 📊 监控和调试

### 健康检查

```bash
# 检查协调器状态
curl http://localhost:8888/health

# 检查所有节点
curl http://localhost:8888/api/v1/nodes
```

### NATS 监控

```bash
# 启动 NATS 监控工具
nats-server -js -m 8222

# 访问 http://localhost:8222
```

### 日志聚合（可选）

```bash
# 使用 journalctl（如果使用 systemd）
journalctl -u openclaw-coordinator -f
journalctl -u openclaw-worker -f
```

## 🐛 常见问题

### 问题 1：NATS 连接失败

```
解决方法：
1. 检查 Tailscale 连接：tailscale ping <主机IP>
2. 检查防火墙设置
3. 确认 NATS 服务器在主机 A 上运行
```

### 问题 2：工作节点无法注册

```
解决方法：
1. 检查配置文件中的 nats_url
2. 查看工作节点日志：logs/worker.log
3. 确认协调器正在运行
```

### 问题 3：任务分发不均

```
解决方法：
1. 检查调度策略配置
2. 查看节点负载：curl http://localhost:8888/api/v1/nodes
3. 调整 worker.max_concurrent_tasks
```

### 问题 4：Python 版本不一致

```bash
# 检查所有机器的 Python 版本
python3 --version

# 建议统一使用 Python 3.10+
```

## 📝 最佳实践

1. **统一环境**
   - 使用相同的 Python 版本
   - 使用 requirements.txt 管理依赖
   - 配置文件纳入版本控制

2. **开发流程**
   - 在主机 A 开发新功能
   - 本地测试通过后提交 Git
   - 在其他机器拉取并验证

3. **日志管理**
   - 每台机器独立日志文件
   - 使用结构化日志格式（JSON）
   - 定期清理旧日志

4. **数据隔离**
   - 开发环境和生产环境分离
   - 每台机器使用独立的数据库文件
   - 使用环境变量管理配置

## 🎯 下一步

- [ ] 设置 systemd 服务实现自动启动
- [ ] 配置监控仪表板
- [ ] 实现配置热重载
- [ ] 添加更多测试用例
- [ ] 优化跨网络性能

---

**相关文档：**
- [部署指南](DEPLOYMENT.md)
- [API 文档](API.md)
- [项目总结](PROJECT_SUMMARY.md)
