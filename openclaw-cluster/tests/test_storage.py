"""
OpenClaw 集群系统 - 存储层测试

测试数据库、仓库和状态管理器功能
"""

import asyncio
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from common.models import (
    ClusterState,
    NodeInfo,
    NodeStatus,
    Task,
    TaskPriority,
    TaskStatus,
    TaskType,
)
from storage.database import Database
from storage.repositories import NodeRepository, TaskRepository
from storage.state_manager import StateManager


# Fixtures
@pytest.fixture
async def temp_db():
    """创建临时数据库"""
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / "test_cluster.db"

    db = Database(str(db_path))
    await db.initialize()

    yield db

    await db.close()
    shutil.rmtree(temp_dir)


@pytest.fixture
async def task_repo(temp_db):
    """创建任务仓库"""
    return TaskRepository(temp_db)


@pytest.fixture
async def node_repo(temp_db):
    """创建节点仓库"""
    return NodeRepository(temp_db)


@pytest.fixture
async def state_manager(temp_db):
    """创建状态管理器"""
    manager = StateManager(temp_db, auto_sync_interval=1)
    await manager.initialize()
    yield manager
    await manager.shutdown()


# 测试数据
@pytest.fixture
def sample_task():
    """创建示例任务"""
    return Task.create(
        task_type=TaskType.BATCH,
        name="test_task",
        description="Test task description",
        required_skills=["python", "data_processing"],
        priority=TaskPriority.NORMAL,
        user_id="test_user",
        parameters={"input": "data.csv", "output": "result.csv"},
    )


@pytest.fixture
def sample_node():
    """创建示例节点"""
    node = NodeInfo(
        node_id="test_node_001",
        hostname="test-host",
        platform="linux",
        arch="x64",
        status=NodeStatus.ONLINE,
        available_skills=["python", "data_processing"],
        max_concurrent_tasks=5,
        ip_address="192.168.1.100",
        port=18789,
        registered_at=datetime.now(),
        last_heartbeat=datetime.now(),
    )
    return node


# 数据库测试
class TestDatabase:
    """测试数据库功能"""

    @pytest.mark.asyncio
    async def test_database_initialization(self, temp_db):
        """测试数据库初始化"""
        stats = await temp_db.get_stats()
        assert stats["task_count"] == 0
        assert stats["node_count"] == 0
        assert stats["task_stats"] == {}
        assert stats["node_stats"] == {}

    @pytest.mark.asyncio
    async def test_database_backup(self, temp_db):
        """测试数据库备份"""
        backup_path = tempfile.mktemp(suffix=".db")
        await temp_db.backup(backup_path)

        backup_file = Path(backup_path)
        assert backup_file.exists()

        # 清理备份文件
        backup_file.unlink()

    @pytest.mark.asyncio
    async def test_database_vacuum(self, temp_db):
        """测试数据库优化"""
        await temp_db.vacuum()
        # 如果没有异常则测试通过
        assert True

    @pytest.mark.asyncio
    async def test_transaction_success(self, temp_db, sample_task):
        """测试成功的事务"""
        operations = [
            {
                "sql": "INSERT INTO tasks (task_id, task_type, name, description, required_skills, status, priority) VALUES (?, ?, ?, ?, ?, ?, ?)",
                "params": (
                    sample_task.task_id,
                    sample_task.task_type.value,
                    sample_task.name,
                    sample_task.description,
                    "[]",  # required_skills serialized
                    sample_task.status.value,
                    sample_task.priority.value,
                ),
            }
        ]

        result = await temp_db.execute_transaction(operations)
        assert result is True


# 任务仓库测试
class TestTaskRepository:
    """测试任务仓库"""

    @pytest.mark.asyncio
    async def test_create_task(self, task_repo, sample_task):
        """测试创建任务"""
        result = await task_repo.create(sample_task)
        assert result is True

        # 验证任务已创建
        retrieved = await task_repo.get(sample_task.task_id)
        assert retrieved is not None
        assert retrieved.task_id == sample_task.task_id
        assert retrieved.name == sample_task.name

    @pytest.mark.asyncio
    async def test_get_task(self, task_repo, sample_task):
        """测试获取任务"""
        await task_repo.create(sample_task)

        retrieved = await task_repo.get(sample_task.task_id)
        assert retrieved is not None
        assert retrieved.task_id == sample_task.task_id
        assert retrieved.task_type == sample_task.task_type
        assert retrieved.status == sample_task.status

    @pytest.mark.asyncio
    async def test_update_task(self, task_repo, sample_task):
        """测试更新任务"""
        await task_repo.create(sample_task)

        # 修改任务
        sample_task.status = TaskStatus.RUNNING
        sample_task.started_at = datetime.now()

        result = await task_repo.update(sample_task)
        assert result is True

        # 验证更新
        retrieved = await task_repo.get(sample_task.task_id)
        assert retrieved.status == TaskStatus.RUNNING
        assert retrieved.started_at is not None

    @pytest.mark.asyncio
    async def test_delete_task(self, task_repo, sample_task):
        """测试删除任务"""
        await task_repo.create(sample_task)

        result = await task_repo.delete(sample_task.task_id)
        assert result is True

        # 验证删除
        retrieved = await task_repo.get(sample_task.task_id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_list_by_status(self, task_repo):
        """测试按状态查询任务"""
        # 创建多个不同状态的任务
        task1 = Task.create(
            task_type=TaskType.BATCH,
            name="pending_task",
            description="Pending task",
            required_skills=["python"],
            status=TaskStatus.PENDING,
        )
        task2 = Task.create(
            task_type=TaskType.BATCH,
            name="running_task",
            description="Running task",
            required_skills=["python"],
            status=TaskStatus.RUNNING,
        )

        await task_repo.create(task1)
        await task_repo.create(task2)

        # 查询PENDING状态的任务
        pending_tasks = await task_repo.list_by_status(TaskStatus.PENDING)
        assert len(pending_tasks) == 1
        assert pending_tasks[0].task_id == task1.task_id

        # 查询RUNNING状态的任务
        running_tasks = await task_repo.list_by_status(TaskStatus.RUNNING)
        assert len(running_tasks) == 1
        assert running_tasks[0].task_id == task2.task_id

    @pytest.mark.asyncio
    async def test_list_by_node(self, task_repo, sample_task):
        """测试按节点查询任务"""
        sample_task.assigned_node = "test_node_001"
        await task_repo.create(sample_task)

        node_tasks = await task_repo.list_by_node("test_node_001")
        assert len(node_tasks) == 1
        assert node_tasks[0].task_id == sample_task.task_id

    @pytest.mark.asyncio
    async def test_count_by_status(self, task_repo):
        """测试统计任务数量"""
        # 创建多个任务
        for i in range(3):
            task = Task.create(
                task_type=TaskType.BATCH,
                name=f"task_{i}",
                description=f"Task {i}",
                required_skills=["python"],
                status=TaskStatus.PENDING,
            )
            await task_repo.create(task)

        count = await task_repo.count_by_status(TaskStatus.PENDING)
        assert count == 3

        total_count = await task_repo.count_by_status()
        assert total_count == 3

    @pytest.mark.asyncio
    async def test_list_pending_tasks_ordered(self, task_repo):
        """测试待处理任务按优先级排序"""
        # 创建不同优先级的任务
        high_priority = Task.create(
            task_type=TaskType.BATCH,
            name="high_task",
            description="High priority task",
            required_skills=["python"],
            priority=TaskPriority.HIGH,
        )
        low_priority = Task.create(
            task_type=TaskType.BATCH,
            name="low_task",
            description="Low priority task",
            required_skills=["python"],
            priority=TaskPriority.LOW,
        )

        await task_repo.create(low_priority)  # 先创建低优先级
        await task_repo.create(high_priority)

        pending_tasks = await task_repo.list_pending_tasks()
        assert len(pending_tasks) == 2
        # 高优先级应该排在前面
        assert pending_tasks[0].priority == TaskPriority.HIGH

    @pytest.mark.asyncio
    async def test_cleanup_old_tasks(self, task_repo):
        """测试清理旧任务"""
        # 创建一个已完成的旧任务
        old_task = Task.create(
            task_type=TaskType.BATCH,
            name="old_task",
            description="Old task",
            required_skills=["python"],
            status=TaskStatus.COMPLETED,
        )
        old_task.completed_at = datetime.now() - timedelta(days=35)
        await task_repo.create(old_task)

        # 创建一个新任务
        new_task = Task.create(
            task_type=TaskType.BATCH,
            name="new_task",
            description="New task",
            required_skills=["python"],
            status=TaskStatus.COMPLETED,
        )
        new_task.completed_at = datetime.now() - timedelta(days=1)
        await task_repo.create(new_task)

        # 清理30天前的任务
        deleted_count = await task_repo.cleanup_old_tasks(days=30)
        assert deleted_count == 1

        # 验证新任务还在
        retrieved = await task_repo.get(new_task.task_id)
        assert retrieved is not None

        # 验证旧任务已删除
        old_retrieved = await task_repo.get(old_task.task_id)
        assert old_retrieved is None


# 节点仓库测试
class TestNodeRepository:
    """测试节点仓库"""

    @pytest.mark.asyncio
    async def test_create_node(self, node_repo, sample_node):
        """测试创建节点"""
        result = await node_repo.create(sample_node)
        assert result is True

        # 验证节点已创建
        retrieved = await node_repo.get(sample_node.node_id)
        assert retrieved is not None
        assert retrieved.node_id == sample_node.node_id
        assert retrieved.hostname == sample_node.hostname

    @pytest.mark.asyncio
    async def test_get_node(self, node_repo, sample_node):
        """测试获取节点"""
        await node_repo.create(sample_node)

        retrieved = await node_repo.get(sample_node.node_id)
        assert retrieved is not None
        assert retrieved.node_id == sample_node.node_id
        assert retrieved.platform == sample_node.platform
        assert retrieved.status == sample_node.status

    @pytest.mark.asyncio
    async def test_update_node(self, node_repo, sample_node):
        """测试更新节点"""
        await node_repo.create(sample_node)

        # 修改节点
        sample_node.cpu_usage = 75.5
        sample_node.memory_usage = 60.2

        result = await node_repo.update(sample_node)
        assert result is True

        # 验证更新
        retrieved = await node_repo.get(sample_node.node_id)
        assert retrieved.cpu_usage == 75.5
        assert retrieved.memory_usage == 60.2

    @pytest.mark.asyncio
    async def test_delete_node(self, node_repo, sample_node):
        """测试删除节点"""
        await node_repo.create(sample_node)

        result = await node_repo.delete(sample_node.node_id)
        assert result is True

        # 验证删除
        retrieved = await node_repo.get(sample_node.node_id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_list_online_nodes(self, node_repo, sample_node):
        """测试获取在线节点"""
        await node_repo.create(sample_node)

        online_nodes = await node_repo.list_online_nodes()
        assert len(online_nodes) == 1
        assert online_nodes[0].node_id == sample_node.node_id

    @pytest.mark.asyncio
    async def test_update_heartbeat(self, node_repo, sample_node):
        """测试更新心跳"""
        await node_repo.create(sample_node)

        original_heartbeat = sample_node.last_heartbeat
        await asyncio.sleep(0.1)  # 短暂延迟

        result = await node_repo.update_heartbeat(sample_node.node_id)
        assert result is True

        # 验证心跳已更新
        retrieved = await node_repo.get(sample_node.node_id)
        assert retrieved.last_heartbeat > original_heartbeat

    @pytest.mark.asyncio
    async def test_update_status(self, node_repo, sample_node):
        """测试更新状态"""
        await node_repo.create(sample_node)

        result = await node_repo.update_status(sample_node.node_id, NodeStatus.BUSY)
        assert result is True

        # 验证状态已更新
        retrieved = await node_repo.get(sample_node.node_id)
        assert retrieved.status == NodeStatus.BUSY

    @pytest.mark.asyncio
    async def test_find_stale_nodes(self, node_repo, sample_node):
        """测试查找失联节点"""
        await node_repo.create(sample_node)

        # 将节点的最后心跳时间设置为很久以前
        old_heartbeat = datetime.now() - timedelta(seconds=200)
        sample_node.last_heartbeat = old_heartbeat
        await node_repo.update(sample_node)

        # 查找失联节点（超时120秒）
        stale_nodes = await node_repo.find_stale_nodes(timeout_seconds=120)
        assert len(stale_nodes) == 1
        assert stale_nodes[0].node_id == sample_node.node_id

    @pytest.mark.asyncio
    async def test_get_available_nodes(self, node_repo):
        """测试获取可用节点"""
        # 创建两个在线节点，一个满载
        available_node = NodeInfo(
            node_id="node_001",
            hostname="host1",
            platform="linux",
            arch="x64",
            status=NodeStatus.ONLINE,
            available_skills=["python"],
            running_tasks=2,
            max_concurrent_tasks=5,
        )

        busy_node = NodeInfo(
            node_id="node_002",
            hostname="host2",
            platform="linux",
            arch="x64",
            status=NodeStatus.ONLINE,
            available_skills=["python"],
            running_tasks=5,  # 已满载
            max_concurrent_tasks=5,
        )

        await node_repo.create(available_node)
        await node_repo.create(busy_node)

        available_nodes = await node_repo.get_available_nodes()
        assert len(available_nodes) == 1
        assert available_nodes[0].node_id == "node_001"


# 状态管理器测试
class TestStateManager:
    """测试状态管理器"""

    @pytest.mark.asyncio
    async def test_initialization(self, state_manager):
        """测试初始化"""
        assert state_manager.is_initialized is True

        state = await state_manager.get_state()
        assert isinstance(state, ClusterState)
        assert state.total_nodes == 0
        assert state.total_tasks == 0

    @pytest.mark.asyncio
    async def test_add_and_get_node(self, state_manager, sample_node):
        """测试添加和获取节点"""
        result = await state_manager.add_node(sample_node)
        assert result is True

        retrieved = await state_manager.get_node(sample_node.node_id)
        assert retrieved is not None
        assert retrieved.node_id == sample_node.node_id

    @pytest.mark.asyncio
    async def test_add_and_get_task(self, state_manager, sample_task):
        """测试添加和获取任务"""
        result = await state_manager.add_task(sample_task)
        assert result is True

        retrieved = await state_manager.get_task(sample_task.task_id)
        assert retrieved is not None
        assert retrieved.task_id == sample_task.task_id

    @pytest.mark.asyncio
    async def test_get_online_nodes(self, state_manager, sample_node):
        """测试获取在线节点"""
        await state_manager.add_node(sample_node)

        online_nodes = await state_manager.get_online_nodes()
        assert len(online_nodes) == 1
        assert online_nodes[0].node_id == sample_node.node_id

    @pytest.mark.asyncio
    async def test_get_available_nodes(self, state_manager):
        """测试获取可用节点"""
        available_node = NodeInfo(
            node_id="node_001",
            hostname="host1",
            platform="linux",
            arch="x64",
            status=NodeStatus.ONLINE,
            running_tasks=2,
            max_concurrent_tasks=5,
        )

        await state_manager.add_node(available_node)

        available_nodes = await state_manager.get_available_nodes()
        assert len(available_nodes) == 1
        assert available_nodes[0].node_id == "node_001"

    @pytest.mark.asyncio
    async def test_update_node_status(self, state_manager, sample_node):
        """测试更新节点状态"""
        await state_manager.add_node(sample_node)

        result = await state_manager.update_node_status(sample_node.node_id, NodeStatus.BUSY)
        assert result is True

        retrieved = await state_manager.get_node(sample_node.node_id)
        assert retrieved.status == NodeStatus.BUSY

    @pytest.mark.asyncio
    async def test_update_task(self, state_manager, sample_task):
        """测试更新任务"""
        await state_manager.add_task(sample_task)

        sample_task.status = TaskStatus.RUNNING
        sample_task.started_at = datetime.now()

        result = await state_manager.update_task(sample_task)
        assert result is True

        retrieved = await state_manager.get_task(sample_task.task_id)
        assert retrieved.status == TaskStatus.RUNNING

    @pytest.mark.asyncio
    async def test_remove_node(self, state_manager, sample_node):
        """测试移除节点"""
        await state_manager.add_node(sample_node)

        result = await state_manager.remove_node(sample_node.node_id)
        assert result is True

        retrieved = await state_manager.get_node(sample_node.node_id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_remove_task(self, state_manager, sample_task):
        """测试移除任务"""
        await state_manager.add_task(sample_task)

        result = await state_manager.remove_task(sample_task.task_id)
        assert result is True

        retrieved = await state_manager.get_task(sample_task.task_id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_get_pending_tasks(self, state_manager):
        """测试获取待处理任务"""
        # 创建多个任务
        for i in range(3):
            task = Task.create(
                task_type=TaskType.BATCH,
                name=f"task_{i}",
                description=f"Task {i}",
                required_skills=["python"],
                priority=TaskPriority.NORMAL,
            )
            await state_manager.add_task(task)

        pending_tasks = await state_manager.get_pending_tasks()
        assert len(pending_tasks) == 3

    @pytest.mark.asyncio
    async def test_state_version_increment(self, state_manager, sample_node):
        """测试状态版本号递增"""
        initial_version = state_manager.version

        await state_manager.add_node(sample_node)
        assert state_manager.version > initial_version

    @pytest.mark.asyncio
    async def test_sync_to_database(self, state_manager, sample_node):
        """测试同步到数据库"""
        await state_manager.add_node(sample_node, persist=False)

        # 手动触发同步
        result = await state_manager.sync_to_database()
        assert result is True

        # 验证数据已持久化
        retrieved = await state_manager.get_node(sample_node.node_id)
        assert retrieved is not None

    @pytest.mark.asyncio
    async def test_check_stale_nodes(self, state_manager, sample_node):
        """测试检查失联节点"""
        # 设置一个旧的心跳时间
        old_node = NodeInfo(
            node_id="old_node",
            hostname="old-host",
            platform="linux",
            arch="x64",
            status=NodeStatus.ONLINE,
            available_skills=["python"],
            last_heartbeat=datetime.now() - timedelta(seconds=200),
        )

        await state_manager.add_node(old_node)

        # 检查失联节点
        stale_nodes = await state_manager.check_stale_nodes(timeout_seconds=120)
        assert len(stale_nodes) == 1
        assert "old_node" in stale_nodes


# 集成测试
class TestIntegration:
    """集成测试"""

    @pytest.mark.asyncio
    async def test_full_task_lifecycle(self, state_manager):
        """测试完整的任务生命周期"""
        # 1. 创建节点
        node = NodeInfo(
            node_id="worker_001",
            hostname="worker-host",
            platform="linux",
            arch="x64",
            status=NodeStatus.ONLINE,
            available_skills=["python"],
        )
        await state_manager.add_node(node)

        # 2. 创建任务
        task = Task.create(
            task_type=TaskType.BATCH,
            name="integration_test_task",
            description="Integration test task",
            required_skills=["python"],
        )
        await state_manager.add_task(task)

        # 3. 分配任务到节点
        task.assigned_node = node.node_id
        task.status = TaskStatus.SCHEDULED
        task.scheduled_at = datetime.now()
        await state_manager.update_task(task)

        # 4. 开始执行
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        node.running_tasks += 1
        await state_manager.update_task(task)
        await state_manager.update_node(node)

        # 5. 完成任务
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now()
        task.result = {"status": "success", "output": "test_output"}
        node.running_tasks -= 1
        node.total_tasks_processed += 1
        node.successful_tasks += 1
        await state_manager.update_task(task)
        await state_manager.update_node(node)

        # 验证最终状态
        final_task = await state_manager.get_task(task.task_id)
        assert final_task.status == TaskStatus.COMPLETED
        assert final_task.result is not None

        final_node = await state_manager.get_node(node.node_id)
        assert final_node.running_tasks == 0
        assert final_node.total_tasks_processed == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
