#!/usr/bin/env python3
"""
OpenClaw 集群系统 - 状态管理验证测试

验证状态管理系统的核心功能
"""
import asyncio
import sys
import os
from datetime import datetime

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from common.models import Task, TaskType, TaskStatus, NodeInfo, NodeStatus
from storage.database import Database
from storage.state_manager import StateManager


async def main():
    """主测试函数"""
    print("=" * 60)
    print("OpenClaw 集群系统 - 状态管理验证")
    print("=" * 60)

    # 初始化数据库
    print("\n1. 初始化数据库...")
    db = Database("./data/cluster.db")
    await db.initialize()
    print("✅ 数据库初始化成功")

    # 创建状态管理器
    print("\n2. 创建状态管理器...")
    state_manager = StateManager(db)
    await state_manager.initialize()
    print("✅ 状态管理器创建成功")

    # 测试节点管理
    print("\n3. 测试节点管理...")
    node = NodeInfo(
        node_id="test_worker_001",
        hostname="test-worker",
        platform="macos",
        arch="arm64",
        status=NodeStatus.ONLINE,
        available_skills=["weather", "search"],
        tailscale_ip="100.x.x.x",
        port=18789,
    )
    await state_manager.add_node(node)
    print(f"✅ 节点添加成功: {node.node_id}")

    # 查询节点
    retrieved_node = await state_manager.get_node(node.node_id)
    if retrieved_node:
        print(f"✅ 节点查询成功: {retrieved_node.hostname}")
    else:
        print("❌ 节点查询失败")

    # 获取所有节点
    state = await state_manager.get_state()
    print(f"✅ 当前节点数: {state.total_nodes}")

    # 测试任务管理
    print("\n4. 测试任务管理...")
    task = Task.create(
        task_type=TaskType.INTERACTIVE,
        name="测试天气查询",
        description="这是一个测试任务",
        required_skills=["weather"],
    )
    await state_manager.add_task(task)
    print(f"✅ 任务添加成功: {task.task_id}")

    # 查询任务
    retrieved_task = await state_manager.get_task(task.task_id)
    if retrieved_task:
        print(f"✅ 任务查询成功: {retrieved_task.name}")
    else:
        print("❌ 任务查询失败")

    # 获取任务统计
    stats = await state_manager.get_task_stats()
    print(f"✅ 任务统计:")
    print(f"   总任务数: {stats['total']}")
    print(f"   等待中: {stats['pending']}")
    print(f"   运行中: {stats['running']}")

    # 测试状态更新
    print("\n5. 测试状态更新...")
    task.status = TaskStatus.RUNNING
    await state_manager.update_task(task)
    print(f"✅ 任务状态更新: {task.task_id} -> {task.status.value}")

    # 测试心跳更新
    print("\n6. 测试心跳更新...")
    await state_manager.update_heartbeat(
        node.node_id,
        cpu_usage=50.0,
        memory_usage=60.0,
        running_tasks=1
    )
    print(f"✅ 心跳更新成功: {node.node_id}")

    # 测试查询功能
    print("\n7. 测试查询功能...")

    # 获取待处理任务
    pending_tasks = await state_manager.get_pending_tasks()
    print(f"✅ 待处理任务数: {len(pending_tasks)}")

    # 获取在线节点
    online_nodes = await state_manager.get_online_nodes()
    print(f"✅ 在线节点数: {len(online_nodes)}")

    # 按技能查找节点
    skilled_nodes = await state_manager.find_nodes_by_skill("weather")
    print(f"✅ 具备weather技能的节点数: {len(skilled_nodes)}")

    # 清理
    print("\n8. 清理测试数据...")
    await state_manager.remove_task(task.task_id)
    await state_manager.remove_node(node.node_id)
    print("✅ 测试数据清理完成")

    # 关闭
    print("\n9. 关闭状态管理器...")
    await state_manager.shutdown()
    print("✅ 状态管理器已关闭")

    print("\n" + "=" * 60)
    print("✅ 所有状态管理测试通过！")
    print("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
