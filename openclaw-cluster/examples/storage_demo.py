"""
OpenClaw 集群系统 - 存储层使用示例

演示如何使用状态管理器和数据仓库
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

# 添加父目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from common.models import Task, TaskType, TaskStatus, TaskPriority, NodeInfo, NodeStatus
from storage.database import Database
from storage.state_manager import StateManager


async def main():
    """主函数"""
    print("=" * 60)
    print("OpenClaw 集群系统 - 存储层演示")
    print("=" * 60)

    # 1. 初始化数据库和状态管理器
    print("\n[1] 初始化数据库和状态管理器...")
    db_path = "./demo_cluster.db"
    db = Database(db_path)
    state_manager = StateManager(db, auto_sync_interval=10)

    await state_manager.initialize()
    print("✓ 状态管理器初始化完成")

    # 2. 创建工作节点
    print("\n[2] 创建工作节点...")
    nodes = [
        NodeInfo(
            node_id="worker_001",
            hostname="worker-host-1",
            platform="linux",
            arch="x64",
            status=NodeStatus.ONLINE,
            available_skills=["python", "data_processing", "ml_training"],
            max_concurrent_tasks=5,
            ip_address="192.168.1.101",
            port=18789,
            registered_at=datetime.now(),
            last_heartbeat=datetime.now(),
        ),
        NodeInfo(
            node_id="worker_002",
            hostname="worker-host-2",
            platform="linux",
            arch="arm64",
            status=NodeStatus.ONLINE,
            available_skills=["python", "web_scraping", "image_processing"],
            max_concurrent_tasks=3,
            ip_address="192.168.1.102",
            port=18789,
            registered_at=datetime.now(),
            last_heartbeat=datetime.now(),
        ),
    ]

    for node in nodes:
        await state_manager.add_node(node)
        print(f"  ✓ 节点 {node.node_id} 已注册 ({node.platform}-{node.arch})")

    # 3. 创建任务
    print("\n[3] 创建任务...")
    tasks = [
        Task.create(
            task_type=TaskType.BATCH,
            name="data_processing_task",
            description="处理大数据集",
            required_skills=["python", "data_processing"],
            priority=TaskPriority.HIGH,
            user_id="user_001",
            parameters={"input": "data.csv", "output": "result.csv"},
        ),
        Task.create(
            task_type=TaskType.COMPUTE_INTENSIVE,
            name="ml_training_task",
            description="训练机器学习模型",
            required_skills=["python", "ml_training"],
            priority=TaskPriority.NORMAL,
            user_id="user_002",
            parameters={"model": "transformer", "epochs": 100},
        ),
        Task.create(
            task_type=TaskType.IO_INTENSIVE,
            name="web_scraping_task",
            description="爬取网页数据",
            required_skills=["python", "web_scraping"],
            priority=TaskPriority.LOW,
            user_id="user_001",
            parameters={"url": "https://example.com", "pages": 100},
        ),
    ]

    for task in tasks:
        await state_manager.add_task(task)
        print(f"  ✓ 任务 {task.task_id} 已创建 ({task.task_type.value})")

    # 4. 查询集群状态
    print("\n[4] 查询集群状态...")
    state = await state_manager.get_state()
    print(f"  总节点数: {state.total_nodes}")
    print(f"  在线节点数: {state.online_nodes}")
    print(f"  总任务数: {state.total_tasks}")
    print(f"  运行中任务数: {state.running_tasks}")

    # 5. 查询可用节点
    print("\n[5] 查询可用节点...")
    available_nodes = await state_manager.get_available_nodes()
    print(f"  可用节点数: {len(available_nodes)}")
    for node in available_nodes:
        print(
            f"    - {node.node_id}: {len(node.available_skills)} 个技能, "
            f"{node.running_tasks}/{node.max_concurrent_tasks} 任务运行中"
        )

    # 6. 模拟任务调度
    print("\n[6] 模拟任务调度...")
    pending_tasks = await state_manager.get_pending_tasks()
    for i, task in enumerate(pending_tasks):
        # 找到合适的节点
        suitable_nodes = [
            node
            for node in available_nodes
            if any(skill in node.available_skills for skill in task.required_skills)
        ]

        if suitable_nodes:
            # 选择负载最轻的节点
            selected_node = min(suitable_nodes, key=lambda n: n.running_tasks)

            # 分配任务
            task.assigned_node = selected_node.node_id
            task.status = TaskStatus.SCHEDULED
            task.scheduled_at = datetime.now()
            await state_manager.update_task(task)

            # 更新节点
            node = await state_manager.get_node(selected_node.node_id)
            node.running_tasks += 1
            await state_manager.update_node(node)

            print(
                f"  ✓ 任务 {task.name} 已调度到节点 {selected_node.node_id} "
                f"({selected_node.platform}-{selected_node.arch})"
            )

    # 7. 模拟任务执行
    print("\n[7] 模拟任务执行...")
    running_tasks = await state_manager.get_task(tasks[0].task_id)
    if running_tasks:
        running_tasks.status = TaskStatus.RUNNING
        running_tasks.started_at = datetime.now()
        await state_manager.update_task(running_tasks)
        print(f"  ✓ 任务 {running_tasks.name} 开始执行")

        # 模拟任务完成
        await asyncio.sleep(0.1)
        running_tasks.status = TaskStatus.COMPLETED
        running_tasks.completed_at = datetime.now()
        running_tasks.result = {"status": "success", "processed": 1000}
        await state_manager.update_task(running_tasks)
        print(f"  ✓ 任务 {running_tasks.name} 执行完成")

        # 更新节点统计
        node = await state_manager.get_node(running_tasks.assigned_node)
        if node:
            node.running_tasks -= 1
            node.total_tasks_processed += 1
            node.successful_tasks += 1
            await state_manager.update_node(node)
            print(f"  ✓ 节点 {node.node_id} 统计已更新")

    # 8. 查询任务状态
    print("\n[8] 查询任务状态...")
    for task in tasks:
        t = await state_manager.get_task(task.task_id)
        if t:
            print(
                f"  {t.name}: {t.status.value} "
                f"(优先级: {t.priority.value}, "
                f"分配节点: {t.assigned_node or '未分配'})"
            )

    # 9. 检查失联节点
    print("\n[9] 检查失联节点...")
    stale_nodes = await state_manager.check_stale_nodes(timeout_seconds=120)
    if stale_nodes:
        print(f"  发现 {len(stale_nodes)} 个失联节点")
    else:
        print("  ✓ 所有节点都正常")

    # 10. 获取数据库统计信息
    print("\n[10] 获取数据库统计信息...")
    stats = await db.get_stats()
    print(f"  数据库路径: {stats['db_path']}")
    print(f"  数据库大小: {stats['db_size']} 字节")
    print(f"  任务总数: {stats['task_count']}")
    print(f"  节点总数: {stats['node_count']}")
    print(f"  任务状态分布: {stats['task_stats']}")
    print(f"  节点状态分布: {stats['node_stats']}")

    # 关闭
    print("\n[11] 关闭状态管理器...")
    await state_manager.shutdown()
    print("✓ 状态管理器已关闭")

    print("\n" + "=" * 60)
    print("演示完成！")
    print("=" * 60)

    # 清理演示数据库
    print(f"\n提示: 演示数据库保存在: {db_path}")
    print("如需清理，请手动删除该文件。")


if __name__ == "__main__":
    asyncio.run(main())
