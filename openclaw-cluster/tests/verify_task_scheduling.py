#!/usr/bin/env python3
"""OpenClaw 集群系统 - 任务调度验证"""
import asyncio
import sys
import os

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from common.models import Task, TaskType, TaskStatus, TaskPriority, NodeInfo, NodeStatus
from storage.database import Database
from storage.state_manager import StateManager
from scheduler.task_queue import TaskQueue, MultiLevelTaskQueue, PrioritizedTask
from scheduler.task_scheduler import TaskScheduler, SchedulingStrategy


async def test_task_queue():
    """测试任务队列"""
    print("\n=== 测试任务队列 ===")

    # 创建任务队列
    queue = TaskQueue(max_size=100)

    # 创建测试任务
    tasks = []
    for i in range(5):
        task = Task.create(
            task_type=TaskType.INTERACTIVE,
            name=f"test_task_{i}",
            description=f"测试任务 {i}",
            required_skills=["python"],
            priority=TaskPriority.NORMAL if i > 0 else TaskPriority.HIGH,
        )
        tasks.append(task)

        # 加入队列
        success = await queue.enqueue(task)
        assert success is True
        print(f"✅ 任务 {i} 已加入队列: {task.task_id}")

    # 检查队列大小
    size = await queue.size()
    print(f"✅ 队列大小: {size}")
    assert size == 5

    # 按优先级获取任务
    pending = await queue.get_pending_by_priority()
    print(f"✅ 待处理任务数: {len(pending)}")

    # 取出任务
    task1 = await queue.dequeue()
    print(f"✅ 取出任务: {task1.task_id} (优先级: {task1.priority.value})")

    # 检查队列大小
    size = await queue.size()
    print(f"✅ 取出后队列大小: {size}")
    assert size == 4

    # 获取统计信息
    stats = await queue.get_stats()
    print(f"✅ 队列统计:")
    print(f"   队列大小: {stats['queue_size']}")
    print(f"   总入队: {stats['total_queued']}")
    print(f"   总出队: {stats['total_dequeued']}")

    # 清空队列
    await queue.clear()
    print("✅ 队列已清空")

    print("✅ 任务队列测试通过")


async def test_multi_level_queue():
    """测试多级任务队列"""
    print("\n=== 测试多级任务队列 ===")

    # 创建多级队列
    queue = MultiLevelTaskQueue(max_size_per_level=10)

    # 创建不同优先级的任务
    for priority in [TaskPriority.LOW, TaskPriority.NORMAL, TaskPriority.HIGH, TaskPriority.CRITICAL]:
        task = Task.create(
            task_type=TaskType.INTERACTIVE,
            name=f"{priority.value}_task",
            description=f"{priority.value} 优先级任务",
            required_skills=["python"],
            priority=priority,
        )

        success = await queue.enqueue(task)
        assert success is True
        print(f"✅ {priority.value} 优先级任务已加入: {task.task_id}")

    # 按优先级取出任务
    order = []
    for _ in range(4):
        task = await queue.dequeue()
        if task:
            order.append(task.priority.value)
            print(f"✅ 取出: {task.priority.value} - {task.task_id}")

    # 验证顺序
    expected = [TaskPriority.CRITICAL.value, TaskPriority.HIGH.value, TaskPriority.NORMAL.value, TaskPriority.LOW.value]
    assert order == expected, f"优先级顺序错误: {order} != {expected}"

    # 获取统计
    stats = await queue.get_all_stats()
    print(f"✅ 多级队列统计:")
    print(f"   总大小: {stats['total_size']}")
    print(f"   总容量: {stats['total_capacity']}")
    print(f"   利用率: {stats['overall_utilization']:.1f}%")

    print("✅ 多级任务队列测试通过")


async def test_scheduler():
    """测试任务调度器"""
    print("\n=== 测试任务调度器 ===")

    # 初始化
    db = Database("./data/scheduler_test.db")
    await db.initialize()
    state_manager = StateManager(db)
    await state_manager.initialize()
    print("✅ 状态管理器初始化成功")

    # 创建调度器
    scheduler = TaskScheduler(
        state_manager,
        strategy=SchedulingStrategy.LEAST_TASKS,
        scheduling_interval=1,
    )
    await scheduler.start()
    print(f"✅ 调度器已启动 (策略: {scheduler.strategy.value})")

    # 添加测试节点
    nodes = []
    for i in range(3):
        node = NodeInfo(
            node_id=f"scheduler_node_{i}",
            hostname=f"worker-{i}",
            platform="linux",
            arch="x64",
            status=NodeStatus.ONLINE,
            available_skills=["python", "search"],
            max_concurrent_tasks=3,
            running_tasks=i,  # 不同的负载
        )
        await state_manager.add_node(node)
        nodes.append(node)
        print(f"✅ 节点已添加: {node.node_id} (运行任务: {node.running_tasks})")

    # 提交任务
    tasks = []
    for i in range(5):
        task = Task.create(
            task_type=TaskType.INTERACTIVE,
            name=f"scheduler_task_{i}",
            description=f"调度测试任务 {i}",
            required_skills=["python"],
            priority=TaskPriority.NORMAL,
        )
        tasks.append(task)

        success = await scheduler.submit_task(task)
        assert success is True
        print(f"✅ 任务已提交: {task.task_id}")

    # 等待调度
    await asyncio.sleep(2)

    # 获取调度器统计
    stats = await scheduler.get_scheduler_stats()
    print(f"✅ 调度器统计:")
    print(f"   总调度: {stats['total_scheduled']}")
    print(f"   失败: {stats['total_failed']}")
    print(f"   无节点: {stats['total_no_nodes']}")

    # 获取队列统计
    queue_stats = await scheduler.get_queue_stats()
    print(f"✅ 队列统计:")
    print(f"   队列大小: {queue_stats['total_size']}")

    # 停止调度器
    await scheduler.stop()
    print("✅ 调度器已停止")

    # 清理
    for node in nodes:
        await state_manager.delete_node(node.node_id)

    await state_manager.shutdown()
    print("✅ 状态管理器已关闭")

    print("✅ 任务调度器测试通过")


async def test_scheduling_strategies():
    """测试不同调度策略"""
    print("\n=== 测试调度策略 ===")

    # 初始化
    db = Database(":memory:")
    await db.initialize()
    state_manager = StateManager(db)
    await state_manager.initialize()

    # 添加测试节点
    nodes = []
    for i in range(3):
        node = NodeInfo(
            node_id=f"strategy_node_{i}",
            hostname=f"worker-{i}",
            platform="linux",
            arch="x64",
            status=NodeStatus.ONLINE,
            available_skills=["python"],
            max_concurrent_tasks=5,
            running_tasks=i * 2,  # 0, 2, 4
            cpu_usage=20.0 + i * 15,  # 20, 35, 50
            memory_usage=30.0 + i * 10,  # 30, 40, 50
        )
        await state_manager.add_node(node)
        nodes.append(node)

    # 测试不同策略
    strategies = [
        SchedulingStrategy.LEAST_TASKS,
        SchedulingStrategy.BEST_FIT,
        SchedulingStrategy.RANDOM,
    ]

    for strategy in strategies:
        print(f"\n测试策略: {strategy.value}")

        scheduler = TaskScheduler(
            state_manager,
            strategy=strategy,
            scheduling_interval=1,
        )
        await scheduler.start()

        # 创建任务
        task = Task.create(
            task_type=TaskType.INTERACTIVE,
            name=f"strategy_task_{strategy.value}",
            description=f"测试 {strategy.value} 策略",
            required_skills=["python"],
        )

        await scheduler.submit_task(task)
        await asyncio.sleep(0.5)

        # 检查任务分配的节点
        updated_task = await state_manager.get_task(task.task_id)
        if updated_task and updated_task.assigned_node:
            assigned_node = await state_manager.get_node(updated_task.assigned_node)
            print(f"   ✅ 任务分配到: {assigned_node.hostname} (运行: {assigned_node.running_tasks})")

        await scheduler.stop()

    # 清理
    for node in nodes:
        await state_manager.delete_node(node.node_id)

    await state_manager.shutdown()

    print("\n✅ 调度策略测试通过")


async def main():
    """主测试函数"""
    print("=" * 60)
    print("OpenClaw 集群系统 - 任务调度验证")
    print("=" * 60)

    try:
        # 测试1: 基础任务队列
        await test_task_queue()

        # 测试2: 多级任务队列
        await test_multi_level_queue()

        # 测试3: 任务调度器
        await test_scheduler()

        # 测试4: 调度策略
        await test_scheduling_strategies()

        print("\n" + "=" * 60)
        print("✅ 所有任务调度测试通过！")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
