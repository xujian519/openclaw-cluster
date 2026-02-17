"""
OpenClaw 集群系统 - 任务调度器

实现任务到节点的调度分配和负载均衡
"""

import asyncio
import random
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from common.logging import get_logger
from common.models import NodeInfo, Task, TaskPriority, TaskStatus
from scheduler.task_queue import MultiLevelTaskQueue
from storage.state_manager import StateManager

logger = get_logger(__name__)


class SchedulingStrategy(Enum):
    """调度策略枚举"""

    # 轮询调度
    ROUND_ROBIN = "round_robin"
    # 最少任务优先
    LEAST_TASKS = "least_tasks"
    # 最佳资源匹配
    BEST_FIT = "best_fit"
    # 随机分配
    RANDOM = "random"
    # 基于亲和性
    AFFINITY = "affinity"


class NodeSelectionCriteria:
    """
    节点选择标准

    定义选择节点时的各项权重
    """

    def __init__(
        self,
        cpu_weight: float = 0.3,
        memory_weight: float = 0.3,
        task_weight: float = 0.2,
        affinity_weight: float = 0.2,
    ):
        """
        初始化选择标准

        Args:
            cpu_weight: CPU使用率权重 (反向)
            memory_weight: 内存使用率权重 (反向)
            task_weight: 运行任务数权重 (反向)
            affinity_weight: 亲和性权重 (正向)
        """
        self.cpu_weight = cpu_weight
        self.memory_weight = memory_weight
        self.task_weight = task_weight
        self.affinity_weight = affinity_weight


class TaskScheduler:
    """
    任务调度器

    负责将任务分配到合适的节点
    """

    def __init__(
        self,
        state_manager: StateManager,
        strategy: SchedulingStrategy = SchedulingStrategy.LEAST_TASKS,
        scheduling_interval: int = 1,
    ):
        """
        初始化任务调度器

        Args:
            state_manager: 状态管理器
            strategy: 调度策略
            scheduling_interval: 调度间隔（秒）
        """
        self.state_manager = state_manager
        self.strategy = strategy
        self.scheduling_interval = scheduling_interval

        # 任务队列
        self.task_queue = MultiLevelTaskQueue()

        # 调度状态
        self._is_running = False
        self._scheduler_task: Optional[asyncio.Task] = None

        # 轮询状态
        self._round_robin_index = 0
        self._round_robin_lock = asyncio.Lock()

        # 选择标准
        self.selection_criteria = NodeSelectionCriteria()

        # 统计信息
        self._stats = {
            "total_scheduled": 0,
            "total_failed": 0,
            "total_no_nodes": 0,
        }

    async def start(self):
        """启动调度器"""
        if self._is_running:
            logger.warning("调度器已在运行")
            return

        self._is_running = True
        self._scheduler_task = asyncio.create_task(self._scheduling_loop())
        logger.info(
            f"任务调度器已启动 (策略: {self.strategy.value}, "
            f"间隔: {self.scheduling_interval}秒)"
        )

    async def stop(self):
        """停止调度器"""
        if not self._is_running:
            return

        self._is_running = False

        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass

        logger.info("任务调度器已停止")

    async def submit_task(self, task: Task) -> bool:
        """
        提交任务到调度队列

        Args:
            task: 要调度的任务

        Returns:
            是否成功提交
        """
        # 验证任务状态
        if task.status not in [TaskStatus.PENDING, TaskStatus.SCHEDULED]:
            logger.warning(f"任务状态不正确，无法调度: {task.task_id} ({task.status.value})")
            return False

        # 加入队列
        success = await self.task_queue.enqueue(task)

        if success:
            logger.info(f"任务已提交到调度队列: {task.task_id}")

            # 立即触发一次调度
            asyncio.create_task(self._schedule_once())

        return success

    async def cancel_task(self, task_id: str) -> bool:
        """
        取消任务调度

        Args:
            task_id: 任务ID

        Returns:
            是否成功取消
        """
        # 从队列中移除
        removed = await self.task_queue.remove(task_id)

        if removed:
            logger.info(f"任务已从调度队列移除: {task_id}")

        return removed

    async def _scheduling_loop(self):
        """调度循环"""
        while self._is_running:
            try:
                await self._schedule_once()
                await asyncio.sleep(self.scheduling_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"调度循环出错: {e}", exc_info=True)
                await asyncio.sleep(self.scheduling_interval)

    async def _schedule_once(self):
        """执行一次调度"""
        # 从队列取出任务
        task = await self.task_queue.dequeue()

        if task is None:
            return

        # 查找合适的节点
        node = await self._select_node(task)

        if node is None:
            # 没有可用节点，重新放回队列
            await self.task_queue.enqueue(task)
            self._stats["total_no_nodes"] += 1
            logger.debug(f"没有可用节点，任务重新入队: {task.task_id}")
            return

        # 分配任务到节点
        success = await self._assign_task(task, node)

        if success:
            self._stats["total_scheduled"] += 1
        else:
            self._stats["total_failed"] += 1
            # 分配失败，重新入队
            await self.task_queue.enqueue(task)

    async def _select_node(self, task: Task) -> Optional[NodeInfo]:
        """
        选择执行任务的节点

        Args:
            task: 要分配的任务

        Returns:
            选择的节点，如果没有合适节点则返回None
        """
        # 获取在线可用节点
        available_nodes = await self.state_manager.get_available_nodes()

        if not available_nodes:
            return None

        # 按技能过滤节点
        skilled_nodes = await self._filter_by_skills(available_nodes, task.required_skills)

        if not skilled_nodes:
            logger.warning(f"没有具备所需技能的节点: {task.required_skills}")
            return None

        # 按策略选择节点
        if self.strategy == SchedulingStrategy.ROUND_ROBIN:
            return await self._select_round_robin(skilled_nodes)
        elif self.strategy == SchedulingStrategy.LEAST_TASKS:
            return await self._select_least_tasks(skilled_nodes)
        elif self.strategy == SchedulingStrategy.BEST_FIT:
            return await self._select_best_fit(skilled_nodes)
        elif self.strategy == SchedulingStrategy.RANDOM:
            return await self._select_random(skilled_nodes)
        elif self.strategy == SchedulingStrategy.AFFINITY:
            return await self._select_by_affinity(skilled_nodes, task)
        else:
            return await self._select_least_tasks(skilled_nodes)

    async def _filter_by_skills(
        self, nodes: List[NodeInfo], required_skills: List[str]
    ) -> List[NodeInfo]:
        """
        按技能过滤节点

        Args:
            nodes: 节点列表
            required_skills: 需要的技能列表

        Returns:
            具备所需技能的节点列表
        """
        if not required_skills:
            return nodes

        skilled_nodes = []
        for node in nodes:
            # 检查节点是否具备所有必需技能
            node_skills = set(node.available_skills or [])
            required_set = set(required_skills)

            if required_set.issubset(node_skills):
                skilled_nodes.append(node)

        return skilled_nodes

    async def _select_round_robin(self, nodes: List[NodeInfo]) -> Optional[NodeInfo]:
        """轮询选择节点"""
        async with self._round_robin_lock:
            if not nodes:
                return None

            index = self._round_robin_index % len(nodes)
            self._round_robin_index += 1

            return nodes[index]

    async def _select_least_tasks(self, nodes: List[NodeInfo]) -> Optional[NodeInfo]:
        """选择运行任务最少的节点"""
        if not nodes:
            return None

        # 按运行任务数排序，然后按可用容量排序
        sorted_nodes = sorted(
            nodes, key=lambda n: (n.running_tasks, -(n.max_concurrent_tasks - n.running_tasks))
        )

        return sorted_nodes[0]

    async def _select_best_fit(self, nodes: List[NodeInfo]) -> Optional[NodeInfo]:
        """选择资源最匹配的节点"""
        if not nodes:
            return None

        # 计算每个节点的得分
        def calculate_score(node: NodeInfo) -> float:
            # CPU得分 (使用率越低越好)
            cpu_score = (100 - node.cpu_usage) * self.selection_criteria.cpu_weight

            # 内存得分 (使用率越低越好)
            memory_score = (100 - node.memory_usage) * self.selection_criteria.memory_weight

            # 任务得分 (运行任务越少越好)
            task_score = (
                (node.max_concurrent_tasks - node.running_tasks) / node.max_concurrent_tasks * 100
            ) * self.selection_criteria.task_weight

            # 总分
            total_score = cpu_score + memory_score + task_score

            return total_score

        # 按得分排序
        sorted_nodes = sorted(nodes, key=calculate_score, reverse=True)

        return sorted_nodes[0]

    async def _select_random(self, nodes: List[NodeInfo]) -> Optional[NodeInfo]:
        """随机选择节点"""
        if not nodes:
            return None

        return random.choice(nodes)

    async def _select_by_affinity(self, nodes: List[NodeInfo], task: Task) -> Optional[NodeInfo]:
        """基于亲和性选择节点"""
        if not nodes:
            return None

        # 如果任务有亲和性标签
        if task.affinity_tags:
            # 优先选择标签匹配的节点
            for node in nodes:
                node_tags = set(node.tags or [])
                task_tags = set(task.affinity_tags)

                # 如果节点标签与任务标签有交集
                if node_tags & task_tags:
                    return node

        # 没有亲和性匹配，使用最佳匹配
        return await self._select_best_fit(nodes)

    async def _assign_task(self, task: Task, node: NodeInfo) -> bool:
        """
        将任务分配到节点

        Args:
            task: 要分配的任务
            node: 目标节点

        Returns:
            是否分配成功
        """
        try:
            # 更新任务状态
            task.status = TaskStatus.SCHEDULED
            task.assigned_node = node.node_id
            task.scheduled_at = datetime.now()

            # 保存到状态管理器
            await self.state_manager.update_task(task)

            # 更新节点运行任务数
            node.running_tasks += 1
            await self.state_manager.update_node(node)

            logger.info(
                f"任务已分配到节点: {task.task_id} -> {node.node_id} "
                f"({node.hostname}, 技能: {task.required_skills})"
            )

            return True

        except Exception as e:
            logger.error(f"任务分配失败: {task.task_id} -> {node.node_id}: {e}")
            return False

    async def get_queue_stats(self) -> Dict[str, Any]:
        """
        获取队列统计信息

        Returns:
            统计信息字典
        """
        return await self.task_queue.get_all_stats()

    async def get_scheduler_stats(self) -> Dict[str, Any]:
        """
        获取调度器统计信息

        Returns:
            统计信息字典
        """
        return {
            "strategy": self.strategy.value,
            "is_running": self._is_running,
            "scheduling_interval": self.scheduling_interval,
            **self._stats,
        }

    async def get_pending_tasks(self, limit: int = 50) -> List[Task]:
        """
        获取待调度任务

        Args:
            limit: 限制数量

        Returns:
            待调度任务列表
        """
        all_pending = []

        # 按优先级从各队列获取
        for priority in [
            TaskPriority.CRITICAL,
            TaskPriority.HIGH,
            TaskPriority.NORMAL,
            TaskPriority.LOW,
        ]:
            if hasattr(TaskPriority, priority.value):
                queue = await self.task_queue.get_queue(priority)
                pending = await queue.get_pending_by_priority(limit)
                all_pending.extend(pending)

        return all_pending[:limit]

    async def set_strategy(self, strategy: SchedulingStrategy):
        """
        设置调度策略

        Args:
            strategy: 新的调度策略
        """
        old_strategy = self.strategy
        self.strategy = strategy

        logger.info(f"调度策略已更改: {old_strategy.value} -> {strategy.value}")

    async def set_selection_criteria(self, criteria: NodeSelectionCriteria):
        """
        设置节点选择标准

        Args:
            criteria: 新的选择标准
        """
        self.selection_criteria = criteria

        logger.info("节点选择标准已更新")
