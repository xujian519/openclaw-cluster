#!/usr/bin/env python3
"""
OpenClaw 集群系统 - 集成测试

测试主节点和工作节点的交互
"""

import asyncio
import json
import os
import sys

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.config import NATSConfig
from communication.messages import NodeHeartbeatMessage, TaskAssignMessage, TaskResultMessage
from communication.nats_client import NATSClient


async def test_node_registration():
    """测试节点注册流程"""
    print("\n=== 测试节点注册 ===")

    # 模拟工作节点注册
    worker_config = NATSConfig()
    worker_client = NATSClient(worker_config, "worker_test_1")

    if await worker_client.connect():
        print("✅ 工作节点连接成功")

        # 发送注册消息
        registration_data = {
            "node_id": "worker_test_1",
            "hostname": "test-worker",
            "platform": "macos",
            "arch": "arm64",
            "ip_address": "192.168.1.100",
            "tailscale_ip": "100.x.x.x",
            "port": 18789,
            "max_concurrent_tasks": 5,
            "available_skills": ["weather", "search"],
            "tags": ["mac", "development"],
        }

        await worker_client.publish("cluster.node.register", json.dumps(registration_data).encode())
        print("✅ 注册消息发送成功")

        await worker_client.disconnect()
    else:
        print("❌ 工作节点连接失败")


async def test_heartbeat_flow():
    """测试心跳流程"""
    print("\n=== 测试心跳流程 ===")

    # 工作节点发送心跳
    worker_config = NATSConfig()
    worker_client = NATSClient(worker_config, "worker_test_1")

    if await worker_client.connect():
        print("✅ 工作节点连接成功")

        # 创建心跳消息
        heartbeat = NodeHeartbeatMessage(
            sender_id="worker_test_1",
            cpu_usage=45.5,
            memory_usage=62.3,
            running_tasks=2,
            status="online",
        )

        await worker_client.publish("cluster.heartbeat", heartbeat.to_json().encode())
        print("✅ 心跳消息发送成功")

        await worker_client.disconnect()
    else:
        print("❌ 工作节点连接失败")


async def test_task_assignment():
    """测试任务分配流程"""
    print("\n=== 测试任务分配 ===")

    # 主节点分配任务
    coordinator_config = NATSConfig()
    coordinator_client = NATSClient(coordinator_config, "coordinator_main")

    if await coordinator_client.connect():
        print("✅ 主节点连接成功")

        # 创建任务分配消息
        task = TaskAssignMessage(
            task_id="task_test_001",
            task_type="interactive",
            required_skills=["weather"],
            parameters={"location": "Beijing"},
            sender_id="coordinator_main",
            receiver_id="worker_test_1",
            timeout=30,
        )

        await coordinator_client.publish("cluster.task.assign", task.to_json().encode())
        print("✅ 任务分配消息发送成功")

        await coordinator_client.disconnect()
    else:
        print("❌ 主节点连接失败")


async def test_task_result():
    """测试任务结果流程"""
    print("\n=== 测试任务结果 ===")

    # 工作节点返回结果
    worker_config = NATSConfig()
    worker_client = NATSClient(worker_config, "worker_test_1")

    if await worker_client.connect():
        print("✅ 工作节点连接成功")

        # 创建任务结果消息
        result = TaskResultMessage(
            task_id="task_test_001",
            success=True,
            sender_id="worker_test_1",
            result={"temperature": "25°C", "condition": "晴"},
            execution_time=1.5,
            receiver_id="coordinator_main",
        )

        await worker_client.publish("cluster.task.result", result.to_json().encode())
        print("✅ 任务结果消息发送成功")

        await worker_client.disconnect()
    else:
        print("❌ 工作节点连接失败")


async def test_full_workflow():
    """测试完整工作流程"""
    print("\n=== 测试完整工作流程 ===")

    # 1. 工作节点注册
    print("\n1. 工作节点注册...")
    await test_node_registration()

    await asyncio.sleep(0.5)

    # 2. 工作节点发送心跳
    print("\n2. 工作节点发送心跳...")
    await test_heartbeat_flow()

    await asyncio.sleep(0.5)

    # 3. 主节点分配任务
    print("\n3. 主节点分配任务...")
    await test_task_assignment()

    await asyncio.sleep(0.5)

    # 4. 工作节点返回结果
    print("\n4. 工作节点返回结果...")
    await test_task_result()

    print("\n✅ 完整工作流程测试完成")


async def test_message_patterns():
    """测试消息模式"""
    print("\n=== 测试消息模式 ===")

    config = NATSConfig()
    client = NATSClient(config, "test_client")

    if await client.connect():
        print("✅ 连接成功")

        # 测试不同的消息模式
        patterns = [
            ("cluster.heartbeat", "心跳消息"),
            ("cluster.node.register", "注册消息"),
            ("cluster.task.assign", "任务分配"),
            ("cluster.task.result", "任务结果"),
        ]

        for subject, description in patterns:
            await client.publish(subject, f"测试{description}".encode())
            print(f"✅ 发送 {description} 到 {subject}")

        await client.disconnect()
        print("✅ 所有消息模式测试完成")
    else:
        print("❌ 连接失败")


async def main():
    """主函数"""
    print("OpenClaw 集群系统 - 集成测试")
    print("=" * 50)

    try:
        # 基础流程测试
        await test_node_registration()
        await test_heartbeat_flow()
        await test_task_assignment()
        await test_task_result()

        # 完整工作流程测试
        await test_full_workflow()

        # 消息模式测试
        await test_message_patterns()

        print("\n" + "=" * 50)
        print("✅ 所有集成测试通过！")

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
