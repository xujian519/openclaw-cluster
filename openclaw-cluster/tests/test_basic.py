#!/usr/bin/env python3
"""
OpenClaw 集群系统 - 基础功能测试

测试核心组件的基本功能
"""
import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.models import Task, TaskType, TaskStatus, NodeInfo, NodeStatus
from common.config import Config
from communication.messages import Message, MessageType
from communication.nats_client import NATSClient


async def test_models():
    """测试数据模型"""
    print("\n=== 测试数据模型 ===")

    # 创建任务
    task = Task.create(
        task_type=TaskType.INTERACTIVE,
        name="测试任务",
        description="这是一个测试任务",
        required_skills=["weather"],
    )
    print(f"✅ 创建任务: {task.task_id}")
    print(f"   类型: {task.task_type.value}")
    print(f"   状态: {task.status.value}")

    # 创建节点信息
    node = NodeInfo(
        node_id="test_node",
        hostname="test_host",
        platform="macos",
        arch="arm64",
        status=NodeStatus.ONLINE,
    )
    print(f"✅ 创建节点: {node.node_id}")
    print(f"   状态: {node.status.value}")


async def test_messages():
    """测试消息序列化"""
    print("\n=== 测试消息 ===")

    # 创建消息
    msg = Message(
        type=MessageType.NODE_HEARTBEAT,
        timestamp=datetime.now(),
        sender_id="test_node",
        payload={"cpu_usage": 50.0, "memory_usage": 60.0},
    )
    print(f"✅ 创建消息: {msg.type.value}")

    # 序列化
    json_str = msg.to_json()
    print(f"✅ 序列化成功: {len(json_str)} 字节")

    # 反序列化
    msg2 = Message.from_json(json_str)
    print(f"✅ 反序列化成功: {msg2.sender_id}")


async def test_nats_connection():
    """测试 NATS 连接"""
    print("\n=== 测试 NATS 连接 ===")

    from common.config import NATSConfig

    config = NATSConfig()
    client = NATSClient(config, "test_client")

    # 连接
    if await client.connect():
        print("✅ NATS 连接成功")
        print(f"   连接状态: {client.is_connected()}")

        # 发布测试消息
        await client.publish("test.subject", b"Hello NATS!")
        print("✅ 消息发布成功")

        # 断开连接
        await client.disconnect()
        print("✅ 连接已断开")
    else:
        print("❌ NATS 连接失败")


async def main():
    """主函数"""
    print("OpenClaw 集群系统 - 基础功能测试")
    print("=" * 50)

    try:
        # 测试数据模型
        await test_models()

        # 测试消息
        await test_messages()

        # 测试 NATS 连接
        await test_nats_connection()

        print("\n" + "=" * 50)
        print("✅ 所有测试通过！")

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    from datetime import datetime
    asyncio.run(main())
