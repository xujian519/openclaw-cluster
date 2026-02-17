"""
OpenClaw 集群系统 - 任务队列管理

实现任务队列、优先级调度和队列持久化
"""

import asyncio
import heapq
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

from common.logging import get_logger
from common.models import Task, TaskPriority, TaskStatus, TaskType

logger = get_logger(__name__)


@dataclass(order=True)
class PrioritizedTask:
    """
    优先级任务包装器

    用于在堆队列中按优先级排序
    """

    priority: int = field(compare=True)
    submitted_at: datetime = field(compare=True)
    task: Task = field(compare=False)

    def __init__(self, task: Task):
        """
        初始化优先级任务

        Args:
            task: 原始任务
        """
        self.task = task
        # 优先级数值越小越优先 (0=highest, 5=lowest)
        self.priority = task.priority.value
        self.submitted_at = task.submitted_at


class TaskQueue:
    """
    任务队列管理器

    实现基于优先级的任务队列和队列管理功能
    """

    def __init__(self, max_size: int = 10000):
        """
        初始化任务队列

        Args:
            max_size: 队列最大容量
        """
        self.max_size = max_size

        # 优先级队列 (使用堆)
        self._queue: List[PrioritizedTask] = []

        # 任务索引 (task_id -> PrioritizedTask)
        self._task_index: Dict[str, PrioritizedTask] = {}

        # 按状态分组的任务
        self._tasks_by_status: Dict[TaskStatus, Set[str]] = {status: set() for status in TaskStatus}

        # 按类型分组的任务
        self._tasks_by_type: Dict[TaskType, Set[str]] = {task_type: set() for task_type in TaskType}

        # 按技能需求分组的任务
        self._tasks_by_skill: Dict[str, Set[str]] = {}

        # 队列锁
        self._queue_lock = asyncio.Lock()

        # 统计信息
        self._stats = {
            "total_queued": 0,
            "total_dequeued": 0,
            "total_cancelled": 0,
        }

    async def enqueue(self, task: Task) -> bool:
        """
        将任务加入队列

        Args:
            task: 要加入的任务

        Returns:
            是否成功加入队列
        """
        async with self._queue_lock:
            # 检查队列容量
            if len(self._queue) >= self.max_size:
                logger.warning(f"任务队列已满，拒绝任务: {task.task_id}")
                return False

            # 检查任务是否已存在
            if task.task_id in self._task_index:
                logger.warning(f"任务已存在于队列中: {task.task_id}")
                return False

            # 创建优先级任务
            prioritized_task = PrioritizedTask(task)

            # 加入堆队列
            heapq.heappush(self._queue, prioritized_task)

            # 更新索引
            self._task_index[task.task_id] = prioritized_task

            # 更新状态分组
            self._tasks_by_status[task.status].add(task.task_id)
            self._tasks_by_type[task.task_type].add(task.task_id)

            # 更新技能分组
            for skill in task.required_skills:
                if skill not in self._tasks_by_skill:
                    self._tasks_by_skill[skill] = set()
                self._tasks_by_skill[skill].add(task.task_id)

            # 更新统计
            self._stats["total_queued"] += 1

            logger.info(
                f"任务加入队列: {task.task_id} "
                f"(优先级: {task.priority.value}, 类型: {task.task_type.value})"
            )

            return True

    async def dequeue(self) -> Optional[Task]:
        """
        从队列取出一个优先级最高的任务

        Returns:
            取出的任务，如果队列为空则返回None
        """
        async with self._queue_lock:
            if not self._queue:
                return None

            # 取出最高优先级任务
            prioritized_task = heapq.heappop(self._queue)
            task = prioritized_task.task

            # 从索引中移除
            del self._task_index[task.task_id]

            # 更新状态分组
            self._tasks_by_status[task.status].discard(task.task_id)
            self._tasks_by_type[task.task_type].discard(task.task_id)

            # 更新技能分组
            for skill in task.required_skills:
                self._tasks_by_skill.get(skill, set()).discard(task.task_id)

            # 更新统计
            self._stats["total_dequeued"] += 1

            logger.debug(f"任务从队列取出: {task.task_id}")

            return task

    async def peek(self) -> Optional[Task]:
        """
        查看队列最高优先级任务，但不移除

        Returns:
            最高优先级任务，如果队列为空则返回None
        """
        async with self._queue_lock:
            if not self._queue:
                return None
            return self._queue[0].task

    async def remove(self, task_id: str) -> bool:
        """
        从队列中移除指定任务

        Args:
            task_id: 任务ID

        Returns:
            是否成功移除
        """
        async with self._queue_lock:
            if task_id not in self._task_index:
                return False

            # 获取任务
            prioritized_task = self._task_index[task_id]
            task = prioritized_task.task

            # 从队列中移除 (标记为已删除)
            # 由于heapq不支持直接删除，我们标记为 cancelled
            task.status = TaskStatus.CANCELLED

            # 从索引中移除
            del self._task_index[task_id]

            # 更新状态分组
            self._tasks_by_status[task.status].add(task_id)
            self._tasks_by_status[TaskStatus.PENDING].discard(task_id)
            self._tasks_by_type[task.task_type].discard(task_id)

            # 更新技能分组
            for skill in task.required_skills:
                self._tasks_by_skill.get(skill, set()).discard(task_id)

            # 更新统计
            self._stats["total_cancelled"] += 1

            logger.info(f"任务从队列移除: {task_id}")

            return True

    async def get_by_status(self, status: TaskStatus) -> List[Task]:
        """
        按状态获取任务列表

        Args:
            status: 任务状态

        Returns:
            任务列表
        """
        async with self._queue_lock:
            task_ids = self._tasks_by_status.get(status, set())
            return [self._task_index[tid].task for tid in task_ids if tid in self._task_index]

    async def get_by_type(self, task_type: TaskType) -> List[Task]:
        """
        按类型获取任务列表

        Args:
            task_type: 任务类型

        Returns:
            任务列表
        """
        async with self._queue_lock:
            task_ids = self._tasks_by_type.get(task_type, set())
            return [self._task_index[tid].task for tid in task_ids if tid in self._task_index]

    async def get_by_skill(self, skill: str) -> List[Task]:
        """
        按技能需求获取任务列表

        Args:
            skill: 技能名称

        Returns:
            需要该技能的任务列表
        """
        async with self._queue_lock:
            task_ids = self._tasks_by_skill.get(skill, set())
            return [self._task_index[tid].task for tid in task_ids if tid in self._task_index]

    async def get_pending_by_priority(self, limit: int = 50) -> List[Task]:
        """
        按优先级获取待处理任务

        Args:
            limit: 限制数量

        Returns:
            待处理任务列表 (按优先级排序)
        """
        async with self._queue_lock:
            pending_tasks = [
                pt.task
                for pt in self._queue
                if pt.task.status in [TaskStatus.PENDING, TaskStatus.SCHEDULED]
            ]
            return pending_tasks[:limit]

    async def size(self) -> int:
        """
        获取队列大小

        Returns:
            队列中任务数量
        """
        async with self._queue_lock:
            return len(self._queue)

    async def is_empty(self) -> bool:
        """
        检查队列是否为空

        Returns:
            队列是否为空
        """
        async with self._queue_lock:
            return len(self._queue) == 0

    async def is_full(self) -> bool:
        """
        检查队列是否已满

        Returns:
            队列是否已满
        """
        async with self._queue_lock:
            return len(self._queue) >= self.max_size

    async def get_stats(self) -> Dict[str, Any]:
        """
        获取队列统计信息

        Returns:
            统计信息字典
        """
        async with self._queue_lock:
            # 按状态统计
            status_counts = {}
            for status, task_ids in self._tasks_by_status.items():
                # 只计算队列中的任务
                count = sum(1 for tid in task_ids if tid in self._task_index)
                if count > 0:
                    status_counts[status.value] = count

            # 按类型统计
            type_counts = {}
            for task_type, task_ids in self._tasks_by_type.items():
                count = sum(1 for tid in task_ids if tid in self._task_index)
                if count > 0:
                    type_counts[task_type.value] = count

            return {
                "queue_size": len(self._queue),
                "max_size": self.max_size,
                "utilization": len(self._queue) / self.max_size * 100,
                "status_counts": status_counts,
                "type_counts": type_counts,
                **self._stats,
            }

    async def clear(self):
        """清空队列"""
        async with self._queue_lock:
            self._queue.clear()
            self._task_index.clear()
            for status_set in self._tasks_by_status.values():
                status_set.clear()
            for type_set in self._tasks_by_type.values():
                type_set.clear()
            for skill_set in self._tasks_by_skill.values():
                skill_set.clear()

            logger.info("任务队列已清空")

    async def cleanup_expired(self, timeout_seconds: int = 3600) -> int:
        """
        清理超时任务

        Args:
            timeout_seconds: 超时秒数

        Returns:
            清理的任务数量
        """
        async with self._queue_lock:
            now = datetime.now()
            timeout = timedelta(seconds=timeout_seconds)
            expired_tasks = []

            # 找出超时任务
            for task_id, prioritized_task in list(self._task_index.items()):
                task = prioritized_task.task
                if (now - task.submitted_at) > timeout:
                    expired_tasks.append(task_id)

            # 移除超时任务
            for task_id in expired_tasks:
                await self.remove(task_id)

            if expired_tasks:
                logger.warning(f"清理了 {len(expired_tasks)} 个超时任务")

            return len(expired_tasks)


class MultiLevelTaskQueue:
    """
    多级任务队列

    为不同优先级的任务提供独立的队列
    """

    def __init__(self, max_size_per_level: int = 5000):
        """
        初始化多级任务队列

        Args:
            max_size_per_level: 每个优先级级别的最大容量
        """
        # 为每个优先级创建独立队列
        self._queues: Dict[TaskPriority, TaskQueue] = {
            priority: TaskQueue(max_size=max_size_per_level) for priority in TaskPriority
        }

        # 优先级顺序 (从高到低)
        self._priority_order = [
            TaskPriority.CRITICAL,
            TaskPriority.HIGH,
            TaskPriority.NORMAL,
            TaskPriority.LOW,
        ]

    async def enqueue(self, task: Task) -> bool:
        """
        将任务加入对应优先级的队列

        Args:
            task: 要加入的任务

        Returns:
            是否成功加入队列
        """
        queue = self._queues[task.priority]
        return await queue.enqueue(task)

    async def dequeue(self) -> Optional[Task]:
        """
        按优先级从队列取出任务

        先检查高优先级队列，再检查低优先级队列

        Returns:
            取出的任务，如果所有队列都为空则返回None
        """
        # 按优先级顺序检查队列
        for priority in self._priority_order:
            queue = self._queues[priority]
            task = await queue.dequeue()
            if task:
                return task

        return None

    async def get_queue(self, priority: TaskPriority) -> TaskQueue:
        """
        获取指定优先级的队列

        Args:
            priority: 任务优先级

        Returns:
            对应的队列
        """
        return self._queues[priority]

    async def get_all_stats(self) -> Dict[str, Any]:
        """
        获取所有队列的统计信息

        Returns:
            统计信息字典
        """
        stats = {}
        total_size = 0
        total_capacity = 0

        for priority in TaskPriority:
            queue_stats = await self._queues[priority].get_stats()
            stats[priority.value] = queue_stats
            total_size += queue_stats["queue_size"]
            total_capacity += queue_stats["max_size"]

        stats["total_size"] = total_size
        stats["total_capacity"] = total_capacity
        stats["overall_utilization"] = (
            total_size / total_capacity * 100 if total_capacity > 0 else 0
        )

        return stats

    async def clear_all(self):
        """清空所有队列"""
        for queue in self._queues.values():
            await queue.clear()
        logger.info("所有任务队列已清空")
