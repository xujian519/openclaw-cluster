#!/bin/bash
# OpenClaw 集群系统 - 快速启动脚本
# 用于快速启动协调器和一个工作节点进行测试

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 打印带颜色的消息
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# 进入脚本目录
cd "$(dirname "$0")"
cd ..

# 检查 Python 环境
if ! command -v python3 &> /dev/null; then
    print_error "Python 3 未安装，请先安装 Python 3.10+"
    exit 1
fi

# 检查依赖
print_info "检查 Python 依赖..."
if ! python3 -c "import yaml, fastapi, nats" 2>/dev/null; then
    print_info "安装依赖包..."
    pip3 install --user -q pyyaml fastapi uvicorn nats-py aiosqlite httpx structlog 2>&1 | grep -v "^$" || true
fi

# 创建必要的目录
print_info "创建数据目录..."
mkdir -p data skills logs

# 检查是否已有进程运行
if pgrep -f "start_coordinator.py" > /dev/null; then
    print_warning "协调器已在运行"
else
    print_info "启动协调器..."
    # 使用后台进程启动协调器
    python3 scripts/start_coordinator.py > logs/coordinator.log 2>&1 &
    COORDINATOR_PID=$!
    echo $COORDINATOR_PID > .coordinator.pid
    print_info "协调器已启动 (PID: $COORDINATOR_PID)"
fi

# 等待协调器启动
sleep 3

# 启动工作节点
if pgrep -f "start_worker.py" > /dev/null; then
    print_warning "工作节点已在运行"
else
    print_info "启动工作节点..."
    python3 scripts/start_worker.py > logs/worker.log 2>&1 &
    WORKER_PID=$!
    echo $WORKER_PID > .worker.pid
    print_info "工作节点已启动 (PID: $WORKER_PID)"
fi

# 等待服务启动
sleep 2

# 显示访问信息
echo ""
print_info "========================================"
print_info "OpenClaw 集群系统已启动！"
print_info "========================================"
echo ""
print_info "📊 服务地址:"
echo "   - API: http://localhost:8888"
echo "   - 健康检查: http://localhost:8888/health"
echo ""
print_info "📝 查看日志:"
echo "   - 协调器: tail -f logs/coordinator.log"
echo "   - 工作节点: tail -f logs/worker.log"
echo ""
print_info "🛑 停止服务:"
echo "   ./scripts/stop.sh 或按 Ctrl+C"
echo ""

# 保持运行，等待用户中断
trap "echo ''; print_info '正在停止服务...'; kill $(cat .coordinator.id 2>/dev/null) $(cat .worker.pid 2>/dev/null) 2>/dev/null || true; rm -f .coordinator.pid .worker.pid 2>/dev/null; print_info '服务已停止'; exit 0" INT TERM

# 监控进程
while true; do
    sleep 5

    # 检查协调器进程
    if [ -f .coordinator.pid ]; then
        COORDINATOR_PID=$(cat .coordinator.pid)
        if ! ps -p $COORDINATOR_PID > /dev/null 2>&1; then
            print_error "协调器进程已停止"
            rm -f .coordinator.pid
            exit 1
        fi
    fi

    # 检查工作节点进程
    if [ -f .worker.pid ]; then
        WORKER_PID=$(cat .worker.pid)
        if ! ps -p $WORKER_PID > /dev/null 2>&1; then
            print_warning "工作节点进程已停止"
            rm -f .worker.pid
        fi
    fi
done
