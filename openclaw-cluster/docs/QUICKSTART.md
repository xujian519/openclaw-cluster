# OpenClaw 集群系统 - 快速启动指南

## 🚀 5分钟快速开始

### 1. 环境准备

```bash
# 进入项目目录
cd openclaw-cluster

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 启动 NATS

```bash
# 使用 Docker Compose 启动 NATS
docker-compose up -d nats

# 验证 NATS 运行
docker-compose ps
# 应该看到 nats-test-nats-1 ... Up
```

### 3. 配置节点

```bash
# 复制配置文件
cp config/coordinator.yaml.example config/coordinator.yaml
cp config/worker.yaml.example config/worker.yaml

# 编辑配置（可选，使用默认值也可以）
# vim config/coordinator.yaml
```

### 4. 运行测试

```bash
# 运行基础测试
python tests/test_basic.py

# 预期输出：
# ✅ 创建任务: task_xxx
# ✅ 创建节点: test_node
# ✅ 创建消息: node.heartbeat
# ✅ 序列化成功: 149 字节
# ✅ 反序列化成功: test_node
# ✅ NATS 连接成功
# ✅ 消息发布成功
# ✅ 连接已断开
# ✅ 所有测试通过！
```

### 5. 启动系统

#### 方式1: 使用启动脚本（推荐）

```bash
# 给脚本执行权限
chmod +x scripts/start.sh

# 运行启动脚本
./scripts/start.sh

# 按提示选择:
# 1) 只启动主节点
# 2) 只启动工作节点
# 3) 同时启动两者
# 4) 运行测试
```

#### 方式2: 手动启动

```bash
# 终端1: 启动主节点
python -m coordinator.main config/coordinator.yaml

# 终端2: 启动工作节点
python -m worker.main config/worker.yaml
```

---

## 📋 验证安装

### 检查 NATS

```bash
# 访问监控面板
open http://localhost:8222

# 或使用 curl
curl http://localhost:8222/varz
```

### 检查日志

```bash
# 查看日志文件
ls logs/
tail -f logs/openclaw.log
```

---

## 🔧 故障排查

### 问题1: NATS 连接失败

```bash
# 检查 NATS 是否运行
docker-compose ps nats

# 重启 NATS
docker-compose restart nats
```

### 问题2: 模块导入错误

```bash
# 确保在虚拟环境中
source venv/bin/activate

# 检查依赖
pip list | grep nats
```

### 问题3: 端口被占用

```bash
# 检查端口占用
lsof -i :4222
lsof -i :8080

# 更改配置文件中的端口
```

---

## 📚 下一步

- 阅读 [架构设计](architecture.md)
- 查看 [API 文档](api.md)
- 了解 [开发指南](development.md)

---

**需要帮助?**

- 查看 [开发计划](../research/development-plan.md)
- 阅读 [技术验证报告](../research/validation-report.md)
- 检查 [Issue](https://github.com/your-repo/openclaw-cluster/issues)
