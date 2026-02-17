"""
OpenClaw 集群系统 - 状态管理器

管理集群状态的内存缓存和持久化
"""
import asyncio
from typing import Optional, List, Dict, Any, Set
from datetime import datetime, timedelta
from copy import deepcopy

from common.models import (
    Task,
    TaskStatus,
    NodeInfo,
    NodeStatus,
    ClusterState,
)
from common.logging import get_logger
from .database import Database
from .repositories import TaskRepository, NodeRepository

logger = get_logger(__name__)


class StateManager:
    """
    集群状态管理器

    提供状态缓存、持久化和同步功能
    """

    def __init__(self, database: Database, auto_sync_interval: int = 30):
        """
        初始化状态管理器

        Args:
            database: 数据库实例
            auto_sync_interval: 自动同步间隔（秒）
        """
        self.db = database
        self.task_repo = TaskRepository(database)
        self.node_repo = NodeRepository(database)

        # 内存状态缓存
        self._state = ClusterState()
        self._state_lock = asyncio.Lock()
        self._initialized = False

        # 自动同步
        self._auto_sync_interval = auto_sync_interval
        self._sync_task: Optional[asyncio.Task] = None
        self._sync_event = asyncio.Event()

    async def initialize(self) -> bool:
        """
        初始化状态管理器

        从数据库加载状态到内存

        Returns:
            是否初始化成功
        """
        try:
            # 初始化数据库
            await self.db.initialize()

            async with self._state_lock:
                # 加载节点信息
                nodes = await self.node_repo.get_all_nodes()
                for node in nodes:
                    self._state.nodes[node.node_id] = node

                # 加载任务信息（只加载活跃任务）
                active_tasks = await self.task_repo.list_by_status(TaskStatus.RUNNING)
                active_tasks.extend(await self.task_repo.list_by_status(TaskStatus.PENDING))
                active_tasks.extend(await self.task_repo.list_by_status(TaskStatus.SCHEDULED))

                for task in active_tasks:
                    self._state.tasks[task.task_id] = task

                # 更新统计信息
                self._update_statistics()

                self._initialized = True
                self._state.updated_at = datetime.now()

            logger.info(
                f"状态管理器初始化完成: "
                f"{len(self._state.nodes)} 个节点, "
                f"{len(self._state.tasks)} 个任务"
            )

            # 启动自动同步任务
            self._start_auto_sync()

            return True

        except Exception as e:
            logger.error(f"状态管理器初始化失败: {e}")
            return False

    async def get_task_stats(self) -> Dict[str, int]:
        """
        获取任务统计信息

        Returns:
            统计信息字典
        """
        stats = {
            "total": len(self._state.tasks),
            "pending": 0,
            "scheduled": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
        }

        for task in self._state.tasks.values():
            status = task.status.value
            if status in stats:
                stats[status] += 1

        return stats

    async def update_heartbeat(
        self,
        node_id: str,
        cpu_usage: float = 0.0,
        memory_usage: float = 0.0,
        running_tasks: int = 0,
    ):
        """
        更新节点心跳信息

        Args:
            node_id: 节点ID
            cpu_usage: CPU使用率
            memory_usage: 内存使用率
            running_tasks: 运行任务数
        """
        async with self._state_lock:
            if node_id in self._state.nodes:
                node = self._state.nodes[node_id]
                node.cpu_usage = cpu_usage
                node.memory_usage = memory_usage
                node.running_tasks = running_tasks
                node.last_heartbeat = datetime.now()

                self._state.updated_at = datetime.now()

                logger.debug(f"心跳更新: {node_id} (CPU: {cpu_usage}%, 内存: {memory_usage}%)")

    async def shutdown(self):
        """关闭状态管理器"""
        # 停止自动同步
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass

        # 最后同步一次
        await self.sync_to_database()

        # 关闭数据库
        await self.db.close()

        logger.info("状态管理器已关闭")

    def _start_auto_sync(self):
        """启动自动同步任务"""
        if self._sync_task is None or self._sync_task.done():
            self._sync_task = asyncio.create_task(self._auto_sync_loop())
            logger.info(f"自动同步任务已启动 (间隔: {self._auto_sync_interval}秒)")

    async def _auto_sync_loop(self):
        """自动同步循环"""
        while True:
            try:
                # 等待间隔或事件触发
                await asyncio.wait_for(
                    self._sync_event.wait(), timeout=self._auto_sync_interval
                )
                self._sync_event.clear()
            except asyncio.TimeoutError:
                pass

            # 执行同步
            try:
                await self.sync_to_database()
            except Exception as e:
                logger.error(f"自动同步失败: {e}")

    async def get_state(self) -> ClusterState:
        """
        获取集群状态的副本

        Returns:
            集群状态副本
        """
        async with self._state_lock:
            return deepcopy(self._state)

    async def get_node(self, node_id: str) -> Optional[NodeInfo]:
        """
        获取节点信息

        Args:
            node_id: 节点ID

        Returns:
            节点信息或None
        """
        async with self._state_lock:
            return deepcopy(self._state.nodes.get(node_id))

    async def get_task(self, task_id: str) -> Optional[Task]:
        """
        获取任务信息

        Args:
            task_id: 任务ID

        Returns:
            任务信息或None
        """
        async with self._state_lock:
            return deepcopy(self._state.tasks.get(task_id))

    async def get_online_nodes(self) -> List[NodeInfo]:
        """
        获取所有在线节点

        Returns:
            在线节点列表
        """
        async with self._state_lock:
            return [
                deepcopy(node)
                for node in self._state.nodes.values()
                if node.status == NodeStatus.ONLINE
            ]

    async def get_available_nodes(self) -> List[NodeInfo]:
        """
        获取可用节点（在线且未满载）

        Returns:
            可用节点列表
        """
        async with self._state_lock:
            return [
                deepcopy(node)
                for node in self._state.nodes.values()
                if node.status == NodeStatus.ONLINE
                and node.running_tasks < node.max_concurrent_tasks
            ]

    async def find_nodes_by_skill(self, skill: str) -> List[NodeInfo]:
        """
        按技能查找节点

        Args:
            skill: 技能名称

        Returns:
            具备该技能的节点列表
        """
        nodes = await self.node_repo.find_by_skill(skill)
        return nodes

    async def delete_node(self, node_id: str, persist: bool = True) -> bool:
        """
        删除节点（remove_node的别名）

        Args:
            node_id: 节点ID
            persist: 是否持久化到数据库

        Returns:
            是否成功
        """
        return await self.remove_node(node_id, persist)

    async def get_node_stats(self) -> Dict[str, int]:
        """
        获取节点统计信息

        Returns:
            统计信息字典
        """
        async with self._state_lock:
            nodes = list(self._state.nodes.values())

        stats = {
            "total": len(nodes),
            "online": sum(1 for n in nodes if n.status == NodeStatus.ONLINE),
            "offline": sum(1 for n in nodes if n.status == NodeStatus.OFFLINE),
            "busy": sum(
                1
                for n in nodes
                if n.status == NodeStatus.ONLINE and n.running_tasks >= n.max_concurrent_tasks
            ),
        }
        return stats

    async def add_node(self, node: NodeInfo, persist: bool = True) -> bool:
        """
        添加节点

        Args:
            node: 节点信息
            persist: 是否持久化到数据库

        Returns:
            是否成功
        """
        async with self._state_lock:
            self._state.add_node(node)

        if persist:
            success = await self.node_repo.create(node)
            if success:
                self._trigger_sync()
            return success

        return True

    async def update_node(self, node: NodeInfo, persist: bool = True) -> bool:
        """
        更新节点信息

        Args:
            node: 节点信息
            persist: 是否持久化到数据库

        Returns:
            是否成功
        """
        async with self._state_lock:
            if node.node_id in self._state.nodes:
                self._state.nodes[node.node_id] = node
                self._state.version += 1
                self._state.updated_at = datetime.now()

        if persist:
            success = await self.node_repo.update(node)
            if success:
                self._trigger_sync()
            return success

        return True

    async def remove_node(self, node_id: str, persist: bool = True) -> bool:
        """
        移除节点

        Args:
            node_id: 节点ID
            persist: 是否持久化到数据库

        Returns:
            是否成功
        """
        async with self._state_lock:
            self._state.remove_node(node_id)

        if persist:
            success = await self.node_repo.delete(node_id)
            if success:
                self._trigger_sync()
            return success

        return True

    async def update_node_status(
        self, node_id: str, status: NodeStatus, persist: bool = True
    ) -> bool:
        """
        更新节点状态

        Args:
            node_id: 节点ID
            status: 新状态
            persist: 是否持久化到数据库

        Returns:
            是否成功
        """
        async with self._state_lock:
            if node_id in self._state.nodes:
                self._state.update_node_status(node_id, status)

        if persist:
            success = await self.node_repo.update_status(node_id, status)
            if success:
                self._trigger_sync()
            return success

        return True

    async def add_task(self, task: Task, persist: bool = True) -> bool:
        """
        添加任务

        Args:
            task: 任务信息
            persist: 是否持久化到数据库

        Returns:
            是否成功
        """
        async with self._state_lock:
            self._state.add_task(task)

        if persist:
            success = await self.task_repo.create(task)
            if success:
                self._trigger_sync()
            return success

        return True

    async def update_task(self, task: Task, persist: bool = True) -> bool:
        """
        更新任务信息

        Args:
            task: 任务信息
            persist: 是否持久化到数据库

        Returns:
            是否成功
        """
        async with self._state_lock:
            if task.task_id in self._state.tasks:
                self._state.tasks[task.task_id] = task
                self._state.version += 1
                self._state.updated_at = datetime.now()

                # 更新统计信息
                self._update_statistics()

        if persist:
            success = await self.task_repo.update(task)
            if success:
                self._trigger_sync()
            return success

        return True

    async def remove_task(self, task_id: str, persist: bool = True) -> bool:
        """
        移除任务

        Args:
            task_id: 任务ID
            persist: 是否持久化到数据库

        Returns:
            是否成功
        """
        async with self._state_lock:
            if task_id in self._state.tasks:
                del self._state.tasks[task_id]
                self._state.total_tasks = len(self._state.tasks)
                self._state.version += 1
                self._state.updated_at = datetime.now()

                # 更新统计信息
                self._update_statistics()

        if persist:
            success = await self.task_repo.delete(task_id)
            if success:
                self._trigger_sync()
            return success

        return True

    async def get_pending_tasks(self, limit: int = 50) -> List[Task]:
        """
        获取待处理任务

        Args:
            limit: 限制数量

        Returns:
            任务列表
        """
        async with self._state_lock:
            pending_tasks = [
                task
                for task in self._state.tasks.values()
                if task.status in [TaskStatus.PENDING, TaskStatus.SCHEDULED]
            ]
            # 按优先级排序
            pending_tasks.sort(key=lambda t: (t.priority.value, t.submitted_at))
            return deepcopy(pending_tasks[:limit])

    async def sync_to_database(self) -> bool:
        """
        同步状态到数据库

        Returns:
            是否同步成功
        """
        try:
            async with self._state_lock:
                state = deepcopy(self._state)

            # 同步节点
            for node in state.nodes.values():
                await self.node_repo.update(node)

            # 同步任务
            for task in state.tasks.values():
                await self.task_repo.update(task)

            logger.debug("状态同步到数据库完成")
            return True

        except Exception as e:
            logger.error(f"状态同步失败: {e}")
            return False

    async def refresh_from_database(self) -> bool:
        """
        从数据库刷新状态

        Returns:
            是否刷新成功
        """
        try:
            # 重新加载节点
            nodes = await self.node_repo.get_all_nodes()

            # 重新加载活跃任务
            active_tasks = await self.task_repo.list_by_status(TaskStatus.RUNNING)
            active_tasks.extend(await self.task_repo.list_by_status(TaskStatus.PENDING))
            active_tasks.extend(await self.task_repo.list_by_status(TaskStatus.SCHEDULED))

            async with self._state_lock:
                # 更新节点
                for node in nodes:
                    self._state.nodes[node.node_id] = node

                # 更新任务
                for task in active_tasks:
                    self._state.tasks[task.task_id] = task

                # 更新统计信息
                self._update_statistics()
                self._state.version += 1
                self._state.updated_at = datetime.now()

            logger.info("状态从数据库刷新完成")
            return True

        except Exception as e:
            logger.error(f"状态刷新失败: {e}")
            return False

    async def check_stale_nodes(self, timeout_seconds: int = 120) -> List[str]:
        """
        检查失联节点

        Args:
            timeout_seconds: 超时秒数

        Returns:
            失联节点ID列表
        """
        stale_nodes = await self.node_repo.find_stale_nodes(timeout_seconds)
        stale_node_ids = [node.node_id for node in stale_nodes]

        if stale_node_ids:
            logger.warning(f"发现 {len(stale_node_ids)} 个失联节点: {stale_node_ids}")

            # 标记为离线
            for node_id in stale_node_ids:
                await self.update_node_status(node_id, NodeStatus.OFFLINE)

        return stale_node_ids

    def _update_statistics(self):
        """更新统计信息"""
        self._state.total_nodes = len(self._state.nodes)
        self._state.online_nodes = sum(
            1 for node in self._state.nodes.values() if node.status == NodeStatus.ONLINE
        )
        self._state.total_tasks = len(self._state.tasks)
        self._state.running_tasks = sum(
            1 for task in self._state.tasks.values() if task.status == TaskStatus.RUNNING
        )

    def _trigger_sync(self):
        """触发同步事件"""
        self._sync_event.set()

    @property
    def is_initialized(self) -> bool:
        """是否已初始化"""
        return self._initialized

    @property
    def version(self) -> int:
        """获取状态版本号"""
        return self._state.version
