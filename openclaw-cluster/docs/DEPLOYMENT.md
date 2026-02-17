# OpenClaw 集群系统 - 部署指南

> 版本: v1.0.0
> 更新时间: 2026-02-16

## 📋 目录

- [系统要求](#系统要求)
- [快速开始](#快速开始)
- [详细配置](#详细配置)
- [部署模式](#部署模式)
- [运行管理](#运行管理)
- [故障排查](#故障排查)

---

## 系统要求

### 硬件要求

| 组件 | 最低配置 | 推荐配置 |
|------|----------|----------|
| CPU | 2核 | 4核+ |
| 内存 | 4GB | 8GB+ |
| 磁盘 | 20GB | 50GB+ SSD |
| 网络 | 100Mbps | 1Gbps |

### 软件要求

```bash
# 必需软件
Python >= 3.10
pip

# 可选软件
Tailscale (用于VPN网络)
NATS Server (用于消息队列)
```

### Python依赖

```bash
# 进入项目目录
cd openclaw-cluster

# 安装依赖
pip install -r requirements.txt
```

---

## 快速开始

### 方式一：使用默认配置

#### 1. 启动协调器

```bash
# 进入项目目录
cd openclaw-cluster

# 启动协调器（使用默认配置）
python scripts/start_coordinator.py
```

协调器将在 `http://localhost:8888` 启动。

#### 2. 启动工作节点（新终端）

```bash
# 进入项目目录
cd openclaw-cluster

# 启动工作节点（使用默认配置）
python scripts/start_worker.py
```

工作节点将自动连接到协调器。

### 方式二：使用命令行参数

#### 启动协调器

```bash
python scripts/start_coordinator.py \
    --host 0.0.0.0 \
    --port 8888 \
    --db-path ./data/cluster.db
```

#### 启动工作节点

```bash
python scripts/start_worker.py \
    --node-id worker-001 \
    --coordinator-host localhost \
    --coordinator-port 8888 \
    --skills-dir ./skills
```

---

## 详细配置

### 配置文件

创建配置文件 `config.yaml`：

```yaml
# 存储配置
storage:
  type: sqlite
  path: ./data/cluster.db

# 协调器配置
coordinator:
  host: 0.0.0.0
  port: 8888
  heartbeat_timeout: 90
  heartbeat_check_interval: 30

# 工作节点配置
worker:
  max_concurrent_tasks: 5
  heartbeat_interval: 5
  skills_dir: ./skills
  port: 18789

# 通信配置
communication:
  nats_url: nats://localhost:4222

# 日志配置
log:
  level: INFO
  format: json
```

### 使用配置文件

```bash
# 启动协调器
python scripts/start_coordinator.py -c config.yaml

# 启动工作节点
python scripts/start_worker.py -c config.yaml
```

---

## 部署模式

### 单机部署

所有组件运行在同一台机器上：

```bash
# 终端1: 启动协调器
python scripts/start_coordinator.py

# 终端2: 启动工作节点1
python scripts/start_worker.py --node-id worker-001

# 终端3: 启动工作节点2
python scripts/start_worker.py --node-id worker-002
```

### 多机部署

#### 1. 网络配置

确保所有机器可以互相通信：
- 使用 Tailscale 建立VPN网络
- 或配置防火墙规则

#### 2. 启动 NATS Server（可选）

```bash
# 使用 Docker 启动 NATS
docker run -d \
  --name nats \
  -p 4222:4222 \
  -p 8222:8222 \
  nats \
  -js \
  -sd /data
```

#### 3. 启动协调器

```bash
# 在主控机器上
python scripts/start_coordinator.py \
    --host 0.0.0.0 \
    --port 8888
```

#### 4. 启动工作节点

```bash
# 在工作机器1上
python scripts/start_worker.py \
    --coordinator-host <协调器IP> \
    --coordinator-port 8888 \
    --node-id mac-worker-001

# 在工作机器2上
python scripts/start_worker.py \
    --coordinator-host <协调器IP> \
    --coordinator-port 8888 \
    --node-id windows-worker-001
```

---

## 运行管理

### API 访问

#### 健康检查

```bash
curl http://localhost:8888/health
```

#### 获取所有节点

```bash
curl http://localhost:8888/api/v1/nodes
```

#### 获取在线节点

```bash
curl http://localhost:8888/api/v1/nodes/online
```

#### 按技能查找节点

```bash
curl http://localhost:8888/api/v1/nodes/skills/python
```

### 日志查看

日志以 JSON 格式输出到标准输出：

```bash
# 查看协调器日志
python scripts/start_coordinator.py 2>&1 | tee coordinator.log

# 查看工作节点日志
python scripts/start_worker.py 2>&1 | tee worker.log
```

### 优雅关闭

使用 `Ctrl+C` 发送中断信号，服务将优雅关闭。

---

## 故障排查

### 问题1: 无法连接到协调器

**症状**: 工作节点启动后无法连接到协调器

**解决方案**:
1. 检查协调器是否正在运行
2. 检查防火墙设置
3. 检查网络连接
4. 使用 `ping` 和 `telnet` 测试连接

```bash
# 测试网络连接
ping <协调器IP>
telnet <协调器IP> 8888
```

### 问题2: NATS 连接失败

**症状**: 提示 "NATS连接失败"

**解决方案**:
1. 检查 NATS Server 是否运行
2. 检查 NATS URL 是否正确
3. 检查端口是否被占用

```bash
# 检查 NATS 端口
lsof -i :4222

# 测试 NATS 连接
telnet localhost 4222
```

### 问题3: 任务未被调度

**症状**: 提交的任务没有被分配到节点

**解决方案**:
1. 检查节点是否在线
2. 检查节点是否具备所需技能
3. 检查节点是否达到最大并发数

```bash
# 查看在线节点
curl http://localhost:8888/api/v1/nodes/online

# 查看节点技能
curl http://localhost:8888/api/v1/nodes | jq '.[] | .available_skills'
```

### 问题4: 数据库锁定

**症状**: 提示 "database is locked"

**解决方案**:
1. 确保只有一个进程访问数据库
2. 检查是否有僵尸进程
3. 重启服务

```bash
# 查找Python进程
ps aux | grep python

# 杀死僵尸进程
kill -9 <PID>
```

---

## 监控和维护

### 系统监控

#### 查看集群状态

```bash
curl http://localhost:8888/api/v1/cluster/health
```

返回示例：
```json
{
  "total_nodes": 3,
  "online_nodes": 3,
  "total_capacity": 15,
  "available_capacity": 15,
  "timestamp": "2026-02-16T16:00:00Z"
}
```

#### 查看节点健康状态

```bash
curl http://localhost:8888/api/v1/nodes/<node_id>/health
```

### 日志聚合

使用 `jq` 解析 JSON 日志：

```bash
# 查看所有错误日志
python scripts/start_coordinator.py 2>&1 | grep '"level":"ERROR"'

# 查看特定模块的日志
python scripts/start_coordinator.py 2>&1 | grep '"module":"coordinator"'

# 美化输出
python scripts/start_coordinator.py 2>&1 | jq '{timestamp, level, message}'
```

---

## 生产部署建议

### 1. 使用进程管理器

使用 `systemd` 或 `supervisor` 管理服务：

#### systemd 配置示例

```ini
# /etc/systemd/system/openclaw-coordinator.service
[Unit]
Description=OpenClaw Coordinator
After=network.target

[Service]
Type=simple
User=openclaw
WorkingDirectory=/opt/openclaw
ExecStart=/opt/openclaw/venv/bin/python scripts/start_coordinator.py -c /opt/openclaw/config.yaml
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 2. 使用虚拟环境

```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 启动服务
python scripts/start_coordinator.py
```

### 3. 配置日志轮转

使用 `logrotate` 管理日志文件：

```
/opt/openclaw/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
}
```

### 4. 使用反向代理

使用 Nginx 作为反向代理：

```nginx
location /api/v1/ {
    proxy_pass http://localhost:8888/api/v1/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

---

## 安全建议

### 1. 网络安全

- 使用 Tailscale VPN 建立加密网络
- 配置防火墙规则限制访问
- 使用 TLS/SSL 加密通信

### 2. 访问控制

- 配置 API 认证
- 限制管理接口访问
- 使用 API Key

### 3. 数据安全

- 定期备份数据库
- 加密敏感数据
- 设置文件权限

---

## 更新升级

### 更新代码

```bash
# 拉取最新代码
git pull

# 更新依赖
pip install -r requirements.txt --upgrade

# 重启服务
# 使用 systemd
sudo systemctl restart openclaw-coordinator
```

### 数据迁移

```bash
# 备份现有数据
cp data/cluster.db data/cluster.db.backup

# 运行迁移脚本
python scripts/migrate.py
```

---

## 支持

如有问题，请查看：
- 项目文档: `docs/`
- 问题反馈: GitHub Issues
