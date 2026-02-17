#!/bin/bash
# OpenClaw 集群系统 - 停止脚本

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 进入脚本目录
cd "$(dirname "$0")"
cd ..

# 停止协调器
if [ -f .coordinator.pid ]; then
    COORDINATOR_PID=$(cat .coordinator.pid)
    if ps -p $COORDINATOR_PID > /dev/null 2>&1; then
        print_info "停止协调器 (PID: $COORDINATOR_PID)..."
        kill $COORDINATOR_PID
        rm -f .coordinator.pid
    else
        print_warning "协调器进程不存在"
        rm -f .coordinator.pid
    fi
else
    print_info "协调器未运行"
fi

# 停止工作节点
if [ -f .worker.pid ]; then
    WORKER_PID=$(cat .worker.pid)
    if ps -p $WORKER_PID > /dev/null 2>&1; then
        print_info "停止工作节点 (PID: $WORKER_PID)..."
        kill $WORKER_PID
        rm -f .worker.pid
    else
        print_warning "工作节点进程不存在"
        rm -f .worker.pid
    fi
else
    print_info "工作节点未运行"
fi

# 等待进程完全停止
sleep 2

print_info "所有服务已停止"
