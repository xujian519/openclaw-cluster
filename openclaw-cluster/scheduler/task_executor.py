"""
OpenClaw 集群系统 - 任务执行器

处理任务分发到节点和结果收集
"""
import asyncio
import json
from typing import Optional, Dict, Any, Callable, Awaitable
from datetime import datetime
from enum import Enum

from common.models import Task, TaskStatus
from common.logging import get_logger
from storage.state_manager import StateManager
from communication.nats_client import NATSClient
from communication.messages import (
    TaskAssignmentMessage,
    TaskResultMessage,
    TaskStatusMessage,
)

logger = get_logger(__name__)


class ExecutionStatus(Enum):
    """执行状态"""
    PENDING = "pending"
    DISTRIBUTED = "distributed"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class TaskExecution:
    """
    任务执行记录

    跟踪任务的执行状态
    """

    def __init__(self, task: Task, node_id: str):
        """
        初始化任务执行记录

        Args:
            task: 任务对象
            node_id: 执行节点ID
        """
        self.task = task
        self.node_id = node_id
        self.status = ExecutionStatus.PENDING
        self.distributed_at: Optional[datetime] = None
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None
        self.retry_count = 0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "task_id": self.task.task_id,
            "node_id": self.node_id,
            "status": self.status.value,
            "distributed_at": self.distributed_at.isoformat() if self.distributed_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result": self.result,
            "error": self.error,
            "retry_count": self.retry_count,
        }


class TaskExecutor:
    """
    任务执行器

    负责将任务分发到节点并收集结果
    """

    def __init__(
        self,
        state_manager: StateManager,
        nats_client: NATSClient,
        result_timeout: int = 300,
    ):
        """
        初始化任务执行器

        Args:
            state_manager: 状态管理器
            nats_client: NATS客户端
            result_timeout: 结果等待超时（秒）
        """
        self.state_manager = state_manager
        self.nats_client = nats_client
        self.result_timeout = result_timeout

        # 执行中的任务 (task_id -> TaskExecution)
        self._executions: Dict[str, TaskExecution] = {}

        # 等待结果的Future (task_id -> Future)
        self._pending_results: Dict[str, asyncio.Future] = {}

        # 结果回调 (task_id -> callback)
        self._result_callbacks: Dict[str, Callable[[Task, Dict[str, Any]], Awaitable[None]]] = {}

        # 执行锁
        self._execution_lock = asyncio.Lock()

        # 统计信息
        self._stats = {
            "total_distributed": 0,
            "total_completed": 0,
            "total_failed": 0,
            "total_timeout": 0,
        }

        # 订阅结果主题
        self._result_subscription = None

    async def start(self):
        """启动执行器"""
        # 订阅任务结果
        subject = "cluster.task.results.>"
        self._result_subscription = await self.nats_client.subscribe(
            subject,
            self._handle_result_message
        )

        logger.info(f"任务执行器已启动，订阅结果主题: {subject}")

    async def stop(self):
        """停止执行器"""
        if self._result_subscription:
            await self.nats_client.unsubscribe(self._result_subscription)

        # 取消所有等待中的Future
        for future in self._pending_results.values():
            if not future.done():
                future.cancel()

        logger.info("任务执行器已停止")

    async def execute_task(
        self,
        task: Task,
        node_id: str,
        callback: Optional[Callable[[Task, Dict[str, Any]], Awaitable[None]]] = None,
    ) -> bool:
        """
        执行任务

        Args:
            task: 要执行的任务
            node_id: 目标节点ID
            callback: 结果回调函数

        Returns:
            是否成功分发任务
        """
        async with self._execution_lock:
            # 创建执行记录
            execution = TaskExecution(task, node_id)
            self._executions[task.task_id] = execution

            # 注册回调
            if callback:
                self._result_callbacks[task.task_id] = callback

            # 分发任务到节点
            success = await self._distribute_task(task, node_id)

            if not success:
                del self._executions[task.task_id]
                if task.task_id in self._result_callbacks:
                    del self._result_callbacks[task.task_id]
                return False

            execution.status = ExecutionStatus.DISTRIBUTED
            execution.distributed_at = datetime.now()
            self._stats["total_distributed"] += 1

            # 等待结果
            asyncio.create_task(self._wait_for_result(task.task_id))

            logger.info(
                f"任务已分发到节点: {task.task_id} -> {node_id}"
            )

            return True

    async def _distribute_task(self, task: Task, node_id: str) -> bool:
        """
        分发任务到节点

        Args:
            task: 要分发的任务
            node_id: 目标节点ID

        Returns:
            是否分发成功
        """
        try:
            # 创建任务分配消息
            message = TaskAssignmentMessage(
                sender_id="coordinator",
                task_id=task.task_id,
                task_type=task.task_type.value,
                name=task.name,
                description=task.description,
                parameters=task.parameters,
                required_skills=task.required_skills,
                timeout=task.timeout,
                priority=task.priority.value,
            )

            # 发送到目标节点
            subject = f"cluster.nodes.{node_id}.tasks"

            await self.nats_client.publish(subject, message.to_dict())

            logger.debug(f"任务消息已发送到 {subject}")

            return True

        except Exception as e:
            logger.error(f"任务分发失败: {task.task_id} -> {node_id}: {e}")
            return False

    async def _wait_for_result(self, task_id: str):
        """
        等待任务结果

        Args:
            task_id: 任务ID
        """
        # 创建Future等待结果
        future = asyncio.Future()
        self._pending_results[task_id] = future

        try:
            # 等待结果或超时
            await asyncio.wait_for(future, timeout=self.result_timeout)

        except asyncio.TimeoutError:
            logger.warning(f"任务执行超时: {task_id}")
            await self._handle_timeout(task_id)

        except asyncio.CancelledError:
            logger.debug(f"任务等待被取消: {task_id}")

        finally:
            # 清理Future
            self._pending_results.pop(task_id, None)

    async def _handle_result_message(self, message: Dict[str, Any]):
        """
        处理任务结果消息

        Args:
            message: 结果消息
        """
        try:
            # 解析消息
            result = TaskResultMessage.from_dict(message)

            task_id = result.task_id

            # 获取执行记录
            execution = self._executions.get(task_id)

            if execution is None:
                logger.warning(f"收到未知任务的结果: {task_id}")
                return

            # 更新执行状态
            if result.success:
                execution.status = ExecutionStatus.COMPLETED
                execution.result = result.result
                execution.completed_at = datetime.now()
                self._stats["total_completed"] += 1

                # 更新任务状态
                task = execution.task
                task.status = TaskStatus.COMPLETED
                task.completed_at = execution.completed_at
                task.result = json.dumps(result.result) if result.result else None

                await self.state_manager.update_task(task)

                logger.info(f"任务执行完成: {task_id}")

            else:
                execution.status = ExecutionStatus.FAILED
                execution.error = result.error
                execution.completed_at = datetime.now()
                self._stats["total_failed"] += 1

                # 更新任务状态
                task = execution.task
                task.status = TaskStatus.FAILED
                task.completed_at = execution.completed_at
                task.error = result.error

                # 检查是否需要重试
                execution.retry_count += 1
                if execution.retry_count < task.max_retries:
                    task.status = TaskStatus.PENDING
                    task.retry_count = execution.retry_count
                    logger.info(f"任务将重试: {task_id} (第{execution.retry_count}次)")
                else:
                    logger.error(f"任务执行失败（已达最大重试次数）: {task_id}")

                await self.state_manager.update_task(task)

                logger.error(f"任务执行失败: {task_id} - {result.error}")

            # 触发Future
            future = self._pending_results.get(task_id)
            if future and not future.done():
                future.set_result(result)

            # 调用结果回调
            callback = self._result_callbacks.pop(task_id, None)
            if callback:
                try:
                    await callback(execution.task, result.to_dict())
                except Exception as e:
                    logger.error(f"结果回调执行失败: {task_id}: {e}")

        except Exception as e:
            logger.error(f"处理结果消息失败: {e}", exc_info=True)

    async def _handle_timeout(self, task_id: str):
        """
        处理任务超时

        Args:
            task_id: 任务ID
        """
        execution = self._executions.get(task_id)

        if execution is None:
            return

        execution.status = ExecutionStatus.TIMEOUT
        execution.completed_at = datetime.now()
        self._stats["total_timeout"] += 1

        # 更新任务状态
        task = execution.task
        task.status = TaskStatus.FAILED
        task.completed_at = execution.completed_at
        task.error = f"执行超时 (>{self.result_timeout}秒)"

        await self.state_manager.update_task(task)

        logger.warning(f"任务执行超时: {task_id}")

    async def cancel_execution(self, task_id: str) -> bool:
        """
        取消任务执行

        Args:
            task_id: 任务ID

        Returns:
            是否成功取消
        """
        async with self._execution_lock:
            execution = self._executions.get(task_id)

            if execution is None:
                return False

            # 取消等待中的Future
            future = self._pending_results.get(task_id)
            if future and not future.done():
                future.cancel()

            # 清理
            del self._executions[task_id]
            self._result_callbacks.pop(task_id, None)

            logger.info(f"任务执行已取消: {task_id}")

            return True

    async def get_execution_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        获取任务执行状态

        Args:
            task_id: 任务ID

        Returns:
            执行状态信息
        """
        execution = self._executions.get(task_id)

        if execution is None:
            return None

        return execution.to_dict()

    async def get_all_executions(self) -> Dict[str, Dict[str, Any]]:
        """
        获取所有任务执行状态

        Returns:
            所有执行状态
        """
        return {
            task_id: execution.to_dict()
            for task_id, execution in self._executions.items()
        }

    async def get_stats(self) -> Dict[str, Any]:
        """
        获取执行器统计信息

        Returns:
            统计信息
        """
        running_count = sum(
            1 for e in self._executions.values()
            if e.status in [ExecutionStatus.DISTRIBUTED, ExecutionStatus.EXECUTING]
        )

        return {
            "running_executions": running_count,
            "total_executions": len(self._executions),
            **self._stats,
        }
