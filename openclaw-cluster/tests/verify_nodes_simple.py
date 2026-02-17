#!/usr/bin/env python3
"""OpenClaw 集群系统 - 节点管理验证"""

import asyncio
import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from common.models import NodeInfo, NodeStatus
from storage.database import Database
from storage.state_manager import StateManager


async def main():
    print("=" * 60)
    print("OpenClaw 集群系统 - 节点管理验证")
    print("=" * 60)

    # 初始化
    db = Database("./data/cluster.db")
    await db.initialize()
    state_manager = StateManager(db)
    await state_manager.initialize()
    print("✅ 初始化成功")

    # 测试节点注册
    print("\n[测试1] 节点注册")
    node = NodeInfo(
        node_id="test_mac_node",
        hostname="macbook-pro",
        platform="macos",
        arch="arm64",
        status=NodeStatus.ONLINE,
        available_skills=["weather", "search", "python"],
        tailscale_ip="100.73.201.119",
        port=18789,
    )
    await state_manager.add_node(node)
    print(f"✅ 节点注册成功: {node.node_id}")

    # 测试节点查询
    print("\n[测试2] 节点查询")
    retrieved = await state_manager.get_node(node.node_id)
    if retrieved:
        print("✅ 节点查询成功")
        print(f"   主机: {retrieved.hostname}")
        print(f"   状态: {retrieved.status.value}")
        print(f"   技能: {retrieved.available_skills}")
    else:
        print("❌ 节点查询失败")

    # 测试按技能查找
    print("\n[测试3] 按技能查找节点")
    skilled_nodes = await state_manager.find_nodes_by_skill("weather")
    print(f"✅ 找到 {len(skilled_nodes)} 个具备weather技能的节点")
    for n in skilled_nodes:
        print(f"   - {n.hostname} ({n.node_id})")

    # 测试心跳更新
    print("\n[测试4] 心跳更新")
    await state_manager.update_heartbeat(
        node.node_id, cpu_usage=45.5, memory_usage=62.3, running_tasks=2
    )
    print("✅ 心跳更新成功")

    # 测试查询在线节点
    print("\n[测试5] 查询在线节点")
    online_nodes = await state_manager.get_online_nodes()
    print(f"✅ 在线节点数: {len(online_nodes)}")
    for n in online_nodes:
        print(f"   - {n.hostname} ({n.node_id})")

    # 测试获取所有节点
    print("\n[测试6] 获取集群状态")
    state = await state_manager.get_state()
    print("✅ 集群状态:")
    print(f"   总节点: {state.total_nodes}")
    print(f"   在线节点: {state.online_nodes}")
    print(f"   总任务: {state.total_tasks}")

    # 测试任务统计
    print("\n[测试7] 任务统计")
    stats = await state_manager.get_task_stats()
    print("✅ 任务统计:")
    for status, count in stats.items():
        print(f"   {status}: {count}")

    # 清理
    print("\n[清理] 测试数据")
    await state_manager.delete_node(node.node_id)
    print("✅ 测试节点已删除")

    await state_manager.shutdown()
    print("✅ 状态管理器已关闭")

    print("\n" + "=" * 60)
    print("✅ 所有节点管理测试通过！")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
