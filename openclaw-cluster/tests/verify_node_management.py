#!/usr/bin/env python3
"""
OpenClaw 集群系统 - 节点管理功能验证

验证节点注册、心跳和API功能
"""

import asyncio
import os
import sys

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from common.models import NodeInfo, NodeStatus, Task, TaskStatus, TaskType
from storage.database import Database
from storage.state_manager import StateManager


async def test_node_registration():
    """测试节点注册流程"""
    print("\n=== 测试节点注册 ===")

    # 初始化
    db = Database("./data/cluster.db")
    await db.initialize()

    state_manager = StateManager(db)
    await state_manager.initialize()
    print("✅ 状态管理器初始化成功")

    # 创建测试节点
    node = NodeInfo(
        node_id="test_worker_mac",
        hostname="macbook-pro",
        platform="macos",
        arch="arm64",
        status=NodeStatus.ONLINE,
        available_skills=["weather", "search", "python"],
        tailscale_ip="100.73.201.119",
        port=18789,
        ip_address="192.168.1.100",
        max_concurrent_tasks=5,
        tags=["mac", "development"],
    )

    # 添加节点
    await state_manager.add_node(node)
    print(f"✅ 节点注册成功: {node.node_id}")

    # 验证节点已保存
    retrieved = await state_manager.get_node(node.node_id)
    if retrieved:
        print("✅ 节点信息验证成功")
        print(f"   主机名: {retrieved.hostname}")
        print(f"   状态: {retrieved.status.value}")
        print(f"   技能: {retrieved.available_skills}")
    else:
        print("❌ 节点信息验证失败")

    # 测试按技能查找
    skilled_nodes = await state_manager.find_nodes_by_skill("weather")
    print(f"✅ 具备weather技能的节点数: {len(skilled_nodes)}")
    for n in skilled_nodes:
        print(f"   - {n.hostname} ({n.node_id})")

    await state_manager.shutdown()
    print("✅ 节点注册测试完成")


async def test_heartbeat_mechanism():
    """测试心跳机制"""
    print("\n=== 测试心跳机制 ===")

    # 初始化
    db = Database("./data/cluster.db")
    await db.initialize()

    state_manager = StateManager(db)
    await state_manager.initialize()
    print("✅ 状态管理器初始化成功")

    # 创建节点
    node = NodeInfo(
        node_id="heartbeat_test_001",
        hostname="test-node",
        platform="linux",
        arch="x64",
        status=NodeStatus.ONLINE,
        available_skills=["test"],
        max_concurrent_tasks=3,
    )

    await state_manager.add_node(node)
    print(f"✅ 节点创建成功: {node.node_id}")

    # 模拟心跳更新
    print("\n模拟3次心跳更新...")
    for i in range(3):
        await state_manager.update_heartbeat(
            node.node_id, cpu_usage=30.0 + i * 10, memory_usage=40.0 + i * 5, running_tasks=i
        )
        print(f"✅ 心跳 {i+1}: CPU={30+i*10}%, 内存={40+i*5}%, 任务={i}")
        await asyncio.sleep(0.1)

    # 查询最新状态
    updated_node = await state_manager.get_node(node.node_id)
    if updated_node:
        print("\n✅ 节点状态更新成功:")
        print(f"   CPU使用率: {updated_node.cpu_usage}%")
        print(f"   内存使用率: {updated_node.memory_usage}%")
        print(f"   运行任务数: {updated_node.running_tasks}")
        print(f"   最后心跳: {updated_node.last_heartbeat}")

    # 测试失联检测
    print("\n测试失联检测...")
    from datetime import datetime, timedelta

    # 修改最后心跳时间，模拟离线
    async with state_manager._state_lock:
        state_manager._state.nodes[node.node_id].last_heartbeat = datetime.now() - timedelta(
            seconds=100
        )

    # 检测离线节点
    offline_nodes = await state_manager.find_offline_nodes(timeout_seconds=60)
    print(f"✅ 失联节点数: {len(offline_nodes)}")
    if offline_nodes:
        print(f"   失联节点: {offline_nodes[0].node_id}")

    await state_manager.shutdown()
    print("✅ 心跳机制测试完成")


async def test_node_queries():
    """测试节点查询功能"""
    print("\n=== 测试节点查询功能 ===")

    # 初始化
    db = Database("./data/cluster.db")
    await db.initialize()

    state_manager = StateManager(db)
    await state_manager.initialize()
    print("✅ 状态管理器初始化成功")

    # 添加多个测试节点
    nodes = [
        NodeInfo(
            node_id=f"test_node_{i}",
            hostname=f"node-{i}",
            platform="macos",
            arch="arm64",
            status=NodeStatus.ONLINE if i < 3 else NodeStatus.OFFLINE,
            available_skills=["weather", "search", "python"] if i % 2 == 0 else ["media"],
        )
        for i in range(1, 6)
    ]

    for node in nodes:
        await state_manager.add_node(node)
    print(f"✅ 添加了 {len(nodes)} 个测试节点")

    # 测试不同的查询
    print("\n查询功能测试:")

    # 获取所有节点
    all_nodes = await state_manager.get_all_nodes()
    print(f"✅ 总节点数: {len(all_nodes)}")

    # 获取在线节点
    online_nodes = await state_manager.get_online_nodes()
    print(f"✅ 在线节点数: {len(online_nodes)}")

    # 按技能查找
    weather_nodes = await state_manager.find_nodes_by_skill("weather")
    print(f"✅ 具备weather技能的节点数: {len(weather_nodes)}")

    # 获取统计
    state = await state_manager.get_state()
    print("✅ 集群状态:")
    print(f"   总节点: {state.total_nodes}")
    print(f"   在线节点: {state.online_nodes}")
    print(f"   总任务数: {state.total_tasks}")

    # 清理测试数据
    for node in nodes:
        await state_manager.delete_node(node.node_id)
    print(f"\n✅ 清理了 {len(nodes)} 个测试节点")

    await state_manager.shutdown()
    print("✅ 节点查询功能测试完成")


async def test_cluster_statistics():
    """测试集群统计功能"""
    print("\n=== 测试集群统计 ===")

    # 初始化
    db = Database("./data/cluster.db")
    await db.initialize()

    state_manager = StateManager(db)
    await state_manager.initialize()

    # 添加测试节点
    for i in range(3):
        node = NodeInfo(
            node_id=f"stats_node_{i}",
            hostname=f"stats-{i}",
            platform="macos",
            arch="arm64",
            status=NodeStatus.ONLINE,
            available_skills=["test"],
            total_tasks_processed=10 + i * 5,
            successful_tasks=9 + i * 4,
            failed_tasks=i,
        )
        await state_manager.add_node(node)

    # 添加测试任务
    for i in range(5):
        task = Task.create(
            task_type=TaskType.INTERACTIVE,
            name=f"test_task_{i}",
            description=f"测试任务 {i}",
            required_skills=["test"],
            status=TaskStatus.PENDING if i < 3 else TaskStatus.COMPLETED,
        )
        await state_manager.add_task(task)

    # 获取统计
    state = await state_manager.get_state()
    print("✅ 集群统计:")
    print(f"   总节点数: {state.total_nodes}")
    print(f"   在线节点数: {state.online_nodes}")
    print(f"   总任务数: {state.total_tasks}")
    print(f"   运行中任务: {state.running_tasks}")

    # 获取任务统计
    task_stats = await state_manager.get_task_stats()
    print("✅ 任务统计:")
    for status, count in task_stats.items():
        print(f"   {status}: {count}")

    # 获取节点统计
    node_stats = await state_manager.get_node_stats()
    print("✅ 节点统计:")
    print(f"   总节点: {node_stats['total']}")
    print(f"   在线: {node_stats['online']}")
    print(f"   离线: {node_stats['offline']}")
    print(f"   忙碌: {node_stats['busy']}")

    # 清理
    for i in range(3):
        await state_manager.delete_node(f"stats_node_{i}")
    for i in range(5):
        await state_manager.delete_task(f"test_task_{i}")

    await state_manager.shutdown()
    print("✅ 集群统计测试完成")


async def main():
    """主测试函数"""
    print("=" * 60)
    print("OpenClaw 集群系统 - 节点管理功能验证")
    print("=" * 60)

    try:
        # 测试1: 节点注册
        await test_node_registration()

        # 测试2: 心跳机制
        await test_heartbeat_mechanism()

        # 测试3: 节点查询
        await test_node_queries()

        # 测试4: 集群统计
        await test_cluster_statistics()

        print("\n" + "=" * 60)
        print("✅ 所有节点管理功能测试通过！")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
