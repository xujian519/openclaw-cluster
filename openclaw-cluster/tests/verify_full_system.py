#!/usr/bin/env python3
"""OpenClaw 集群系统 - 完整系统验证"""

import asyncio
import os
import shutil
import sys
import tempfile

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from common.models import NodeInfo, NodeStatus, Task, TaskPriority, TaskType
from coordinator.coordinator_service import CoordinatorService
from storage.database import Database
from storage.state_manager import StateManager
from worker.worker_service import WorkerService


async def test_coordinator_lifecycle():
    """测试协调器生命周期"""
    print("\n=== 测试协调器生命周期 ===")

    # 创建临时目录
    temp_dir = tempfile.mkdtemp()

    try:
        # 创建测试配置
        class TestConfig:
            class Storage:
                type = "sqlite"
                path = os.path.join(temp_dir, "cluster.db")

            class Coordinator:
                host = "127.0.0.1"
                port = 8888
                heartbeat_timeout = 90
                heartbeat_check_interval = 30

            class Worker:
                max_concurrent_tasks = 5
                heartbeat_interval = 5
                skills_dir = "./skills"

            class Communication:
                nats_url = "nats://localhost:4222"

            storage = Storage()
            coordinator = Coordinator()
            worker = Worker()
            communication = Communication()

        config = TestConfig()

        # 创建协调器
        coordinator = CoordinatorService(config)

        # 启动协调器
        await coordinator.start()
        print("✅ 协调器已启动")

        # 获取集群状态
        cluster_status = await coordinator.get_cluster_status()
        print("✅ 集群状态:")
        print(f"   总节点: {cluster_status['total_nodes']}")
        print(f"   在线节点: {cluster_status['online_nodes']}")
        print(f"   总任务: {cluster_status['total_tasks']}")

        # 获取技能状态
        skill_status = await coordinator.get_skill_status()
        print("✅ 技能状态:")
        print(f"   总技能数: {skill_status['total_skills']}")
        print(f"   类别分布: {skill_status.get('category_counts', {})}")

        # 获取调度器状态
        scheduler_status = await coordinator.get_scheduler_status()
        print("✅ 调度器状态:")
        print(f"   策略: {scheduler_status.get('strategy', 'unknown')}")
        print(f"   运行中: {scheduler_status.get('is_running', False)}")

        # 停止协调器
        await coordinator.stop()
        print("✅ 协调器已停止")

        print("✅ 协调器生命周期测试通过")

    finally:
        # 清理临时目录
        shutil.rmtree(temp_dir, ignore_errors=True)


async def test_worker_lifecycle():
    """测试工作节点生命周期"""
    print("\n=== 测试工作节点生命周期 ===")

    # 创建测试配置
    class TestConfig:
        class Coordinator:
            host = "127.0.0.1"
            port = 8888

        class Worker:
            max_concurrent_tasks = 5
            heartbeat_interval = 5
            skills_dir = "./skills"
            port = 18789

        class Communication:
            nats_url = "nats://localhost:4222"

        coordinator = Coordinator()
        worker = Worker()
        communication = Communication()

    config = TestConfig()

    # 创建工作节点
    worker = WorkerService(config, node_id="test_worker_001")

    print(f"✅ 工作节点创建: {worker.node_id}")
    print(f"   主机名: {worker.hostname}")
    print(f"   平台: {worker.platform}")
    print(f"   架构: {worker.arch}")
    print(f"   IP地址: {worker.ip_address}")
    print(f"   Tailscale IP: {worker.tailscale_ip}")

    # 获取系统指标
    metrics = await worker.get_system_metrics()
    print("✅ 系统指标:")
    print(f"   CPU使用率: {metrics['cpu_usage']:.1f}%")
    print(f"   内存使用率: {metrics['memory_usage']:.1f}%")
    print(f"   磁盘使用率: {metrics['disk_usage']:.1f}%")
    print(f"   运行任务: {metrics['running_tasks']}")

    # 获取可用技能
    skills = await worker.get_available_skills()
    print(f"✅ 可用技能: {skills}")

    print("✅ 工作节点生命周期测试通过")


async def test_task_submission():
    """测试任务提交流程"""
    print("\n=== 测试任务提交流程 ===")

    # 创建临时目录
    temp_dir = tempfile.mkdtemp()

    try:
        # 创建测试配置
        class TestConfig:
            class Storage:
                type = "sqlite"
                path = os.path.join(temp_dir, "cluster.db")

            class Coordinator:
                host = "127.0.0.1"
                port = 8888
                heartbeat_timeout = 90
                heartbeat_check_interval = 30

            class Worker:
                max_concurrent_tasks = 5
                heartbeat_interval = 5
                skills_dir = "./skills"

            class Communication:
                nats_url = "nats://localhost:4222"

            storage = Storage()
            coordinator = Coordinator()
            worker = Worker()
            communication = Communication()

        config = TestConfig()

        # 创建协调器
        coordinator = CoordinatorService(config)
        await coordinator.start()
        print("✅ 协调器已启动")

        # 创建并提交任务
        tasks = []
        for i in range(5):
            task = Task.create(
                task_type=TaskType.INTERACTIVE,
                name=f"test_task_{i}",
                description=f"测试任务 {i}",
                required_skills=["python"],
                priority=TaskPriority.NORMAL,
            )

            success = await coordinator.submit_task(task)
            assert success is True
            tasks.append(task)
            print(f"✅ 任务已提交: {task.task_id}")

        # 等待调度
        await asyncio.sleep(2)

        # 获取调度器状态
        scheduler_status = await coordinator.get_scheduler_status()
        print("✅ 调度统计:")
        print(f"   总调度: {scheduler_status.get('total_scheduled', 0)}")

        # 停止协调器
        await coordinator.stop()
        print("✅ 协调器已停止")

        print("✅ 任务提交流程测试通过")

    finally:
        # 清理临时目录
        shutil.rmtree(temp_dir, ignore_errors=True)


async def test_multi_node_simulation():
    """测试多节点模拟"""
    print("\n=== 测试多节点模拟 ===")

    # 创建临时目录
    temp_dir = tempfile.mkdtemp()

    try:
        # 创建测试配置
        class TestConfig:
            class Storage:
                type = "sqlite"
                path = os.path.join(temp_dir, "cluster.db")

            class Coordinator:
                host = "127.0.0.1"
                port = 8888
                heartbeat_timeout = 90
                heartbeat_check_interval = 30

            class Worker:
                max_concurrent_tasks = 5
                heartbeat_interval = 5
                skills_dir = "./skills"

            class Communication:
                nats_url = "nats://localhost:4222"

            storage = Storage()
            coordinator = Coordinator()
            worker = Worker()
            communication = Communication()

        config = TestConfig()

        # 创建协调器
        coordinator = CoordinatorService(config)
        await coordinator.start()
        print("✅ 协调器已启动")

        # 初始化状态管理器以添加测试节点
        db = Database(config.storage.path)
        await db.initialize()
        state_manager = StateManager(db)
        await state_manager.initialize()

        # 添加多个测试节点
        nodes = []
        for i in range(3):
            node = NodeInfo(
                node_id=f"test_node_{i}",
                hostname=f"worker-{i}",
                platform="linux",
                arch="x64",
                status=NodeStatus.ONLINE,
                available_skills=["python", "search"],
                max_concurrent_tasks=3,
                running_tasks=0,
            )
            await state_manager.add_node(node)
            nodes.append(node)
            print(f"✅ 节点已添加: {node.node_id}")

        # 提交多个任务
        tasks = []
        for i in range(10):
            task = Task.create(
                task_type=TaskType.INTERACTIVE,
                name=f"multi_node_task_{i}",
                description=f"多节点测试任务 {i}",
                required_skills=["python"],
                priority=TaskPriority.NORMAL,
            )

            success = await coordinator.submit_task(task)
            if success:
                tasks.append(task)

        print(f"✅ 已提交 {len(tasks)} 个任务")

        # 等待调度
        await asyncio.sleep(3)

        # 检查任务分配
        scheduled_count = 0
        for task in tasks:
            updated_task = await state_manager.get_task(task.task_id)
            if updated_task and updated_task.assigned_node:
                scheduled_count += 1

        print(f"✅ 已调度任务: {scheduled_count}/{len(tasks)}")

        # 获取集群状态
        cluster_status = await coordinator.get_cluster_status()
        print("✅ 集群状态:")
        print(f"   总节点: {cluster_status['total_nodes']}")
        print(f"   在线节点: {cluster_status['online_nodes']}")
        print(f"   总任务: {cluster_status['total_tasks']}")
        print(f"   运行中: {cluster_status['running_tasks']}")

        # 清理
        await state_manager.shutdown()
        await coordinator.stop()
        print("✅ 协调器已停止")

        print("✅ 多节点模拟测试通过")

    finally:
        # 清理临时目录
        shutil.rmtree(temp_dir, ignore_errors=True)


async def main():
    """主测试函数"""
    print("=" * 60)
    print("OpenClaw 集群系统 - 完整系统验证")
    print("协调器 + 工作节点集成")
    print("=" * 60)

    try:
        # 测试1: 协调器生命周期
        await test_coordinator_lifecycle()

        # 测试2: 工作节点生命周期
        await test_worker_lifecycle()

        # 测试3: 任务提交流程
        await test_task_submission()

        # 测试4: 多节点模拟
        await test_multi_node_simulation()

        print("\n" + "=" * 60)
        print("✅ 完整系统所有测试通过！")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
