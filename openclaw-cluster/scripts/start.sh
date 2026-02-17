#!/bin/bash
# OpenClaw 集群系统 - 启动脚本

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 项目根目录
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo -e "${GREEN}OpenClaw 集群系统 - 启动脚本${NC}"
echo "=================================="

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}创建虚拟环境...${NC}"
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

# 检查配置文件
if [ ! -f "config/coordinator.yaml" ]; then
    echo -e "${YELLOW}创建主节点配置文件...${NC}"
    cp config/coordinator.yaml.example config/coordinator.yaml
    echo "请编辑 config/coordinator.yaml 配置文件"
fi

# 启动 NATS
echo -e "${GREEN}启动 NATS...${NC}"
if ! docker compose ps | grep -q "nats.*Up"; then
    docker compose up -d nats
    echo "等待 NATS 启动..."
    sleep 3
fi

# 选择启动模式
echo ""
echo "请选择启动模式:"
echo "1) 只启动主节点 (Coordinator)"
echo "2) 只启动工作节点 (Worker)"
echo "3) 同时启动主节点和工作节点"
echo "4) 运行测试"
read -p "请输入选择 (1-4): " choice

case $choice in
    1)
        echo -e "${GREEN}启动主节点...${NC}"
        python -m coordinator.main config/coordinator.yaml
        ;;
    2)
        if [ ! -f "config/worker.yaml" ]; then
            echo -e "${YELLOW}创建工作节点配置文件...${NC}"
            cp config/worker.yaml.example config/worker.yaml
            echo "请编辑 config/worker.yaml 配置文件"
            read -p "按回车继续..."
        fi
        echo -e "${GREEN}启动工作节点...${NC}"
        python -m worker.main config/worker.yaml
        ;;
    3)
        echo -e "${GREEN}启动主节点和工作节点...${NC}"
        # 在后台启动主节点
        python -m coordinator.main config/coordinator.yaml &
        COORD_PID=$!
        echo "主节点 PID: $COORD_PID"

        sleep 2

        # 启动工作节点
        if [ ! -f "config/worker.yaml" ]; then
            cp config/worker.yaml.example config/worker.yaml
        fi
        python -m worker.main config/worker.yaml &
        WORKER_PID=$!
        echo "工作节点 PID: $WORKER_PID"

        echo ""
        echo "按 Ctrl+C 停止所有节点"
        wait $COORD_PID $WORKER_PID
        ;;
    4)
        echo -e "${GREEN}运行测试...${NC}"
        python tests/test_basic.py
        ;;
    *)
        echo -e "${RED}无效选择${NC}"
        exit 1
        ;;
esac
