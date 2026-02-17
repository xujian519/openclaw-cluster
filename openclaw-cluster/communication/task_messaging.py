"""
OpenClaw 集群系统 - 任务消息处理

处理任务分发、结果收集和节点通信的NATS消息
"""

import asyncio
from collections.abc import Awaitable
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from common.logging import get_logger
from common.models import Task
from communication.messages import (
    NodeHeartbeatMessage,
    TaskAssignMessage,
    TaskResultMessage,
)
from communication.nats_client import NATSClient

logger = get_logger(__name__)


class TaskMessaging:
    """
    任务消息处理服务

    管理任务分发和结果收集的消息流
    """

    def __init__(
        self,
        nats_client: NATSClient,
        node_id: str,
    ):
        """
        初始化任务消息服务

        Args:
            nats_client: NATS客户端
            node_id: 当前节点ID
        """
        self.nats_client = nats_client
        self.node_id = node_id

        # 订阅列表
        self._subscriptions: List[str] = []

        # 任务处理器 (task_type -> handler)
        self._task_handlers: Dict[str, Callable] = {}

        # 结果回调 (task_id -> callback)
        self._result_callbacks: Dict[str, Callable] = {}

        # 等待中的任务 (task_id -> Future)
        self._pending_tasks: Dict[str, asyncio.Future] = {}

        # 是否已启动
        self._is_started = False

    async def start(self):
        """启动消息服务"""
        if self._is_started:
            return

        # 订阅任务分配主题
        await self._subscribe_to_tasks()

        # 订阅任务结果主题
        await self._subscribe_to_results()

        self._is_started = True
        logger.info(f"任务消息服务已启动 (节点: {self.node_id})")

    async def stop(self):
        """停止消息服务"""
        if not self._is_started:
            return

        # 取消所有订阅
        for sub_id in self._subscriptions:
            await self.nats_client.unsubscribe(sub_id)

        # 取消所有等待中的Future
        for future in self._pending_tasks.values():
            if not future.done():
                future.cancel()

        self._subscriptions.clear()
        self._is_started = False

        logger.info("任务消息服务已停止")

    async def _subscribe_to_tasks(self):
        """订阅任务分配主题"""
        # 订阅发送到本节点的任务
        subject = f"cluster.nodes.{self.node_id}.tasks"
        sub_id = await self.nats_client.subscribe(
            subject,
            self._handle_task_assignment,
        )
        self._subscriptions.append(sub_id)
        logger.info(f"已订阅任务主题: {subject}")

        # 订阅广播任务
        broadcast_subject = "cluster.tasks.broadcast"
        sub_id = await self.nats_client.subscribe(
            broadcast_subject,
            self._handle_task_assignment,
        )
        self._subscriptions.append(sub_id)
        logger.info(f"已订阅广播任务主题: {broadcast_subject}")

    async def _subscribe_to_results(self):
        """订阅任务结果主题"""
        # 订阅所有任务结果
        subject = "cluster.task.results.>"
        sub_id = await self.nats_client.subscribe(
            subject,
            self._handle_task_result,
        )
        self._subscriptions.append(sub_id)
        logger.info(f"已订阅结果主题: {subject}")

    async def _handle_task_assignment(self, message: Dict[str, Any]):
        """
        处理任务分配消息

        Args:
            message: 任务消息
        """
        try:
            # 解析消息
            task_msg = TaskAssignMessage.from_dict(message)

            logger.info(
                f"收到任务分配: {task_msg.task_id} "
                f"(类型: {task_msg.task_type}, 优先级: {task_msg.priority})"
            )

            # 查找处理器
            handler = self._task_handlers.get(task_msg.task_type)

            if not handler:
                logger.warning(f"未找到任务处理器: {task_msg.task_type}")
                # 发送失败结果
                await self._send_result(
                    task_id=task_msg.task_id,
                    success=False,
                    error=f"未找到任务处理器: {task_msg.task_type}",
                )
                return

            # 执行任务
            try:
                result = await handler(task_msg)

                # 发送成功结果
                await self._send_result(
                    task_id=task_msg.task_id,
                    success=True,
                    result=result,
                )

                logger.info(f"任务执行成功: {task_msg.task_id}")

            except Exception as e:
                logger.error(f"任务执行失败: {task_msg.task_id}: {e}", exc_info=True)

                # 发送失败结果
                await self._send_result(
                    task_id=task_msg.task_id,
                    success=False,
                    error=str(e),
                )

        except Exception as e:
            logger.error(f"处理任务分配消息失败: {e}", exc_info=True)

    async def _handle_task_result(self, message: Dict[str, Any]):
        """
        处理任务结果消息

        Args:
            message: 结果消息
        """
        try:
            # 解析消息
            result_msg = TaskResultMessage.from_dict(message)

            task_id = result_msg.task_id

            logger.debug(f"收到任务结果: {task_id} " f"(成功: {result_msg.success})")

            # 触发等待中的Future
            future = self._pending_tasks.get(task_id)
            if future and not future.done():
                future.set_result(result_msg)

            # 调用结果回调
            callback = self._result_callbacks.pop(task_id, None)
            if callback:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(result_msg)
                    else:
                        callback(result_msg)
                except Exception as e:
                    logger.error(f"结果回调执行失败: {task_id}: {e}")

        except Exception as e:
            logger.error(f"处理任务结果消息失败: {e}", exc_info=True)

    async def register_task_handler(
        self,
        task_type: str,
        handler: Callable[[TaskAssignMessage], Awaitable[Any]],
    ):
        """
        注册任务处理器

        Args:
            task_type: 任务类型
            handler: 处理器函数
        """
        self._task_handlers[task_type] = handler
        logger.info(f"已注册任务处理器: {task_type}")

    async def unregister_task_handler(self, task_type: str):
        """
        注销任务处理器

        Args:
            task_type: 任务类型
        """
        if task_type in self._task_handlers:
            del self._task_handlers[task_type]
            logger.info(f"已注销任务处理器: {task_type}")

    async def send_task(
        self,
        task: Task,
        target_node: str,
        timeout: int = 300,
    ) -> Optional[TaskResultMessage]:
        """
        发送任务到指定节点

        Args:
            task: 要发送的任务
            target_node: 目标节点ID
            timeout: 超时时间（秒）

        Returns:
            任务结果，如果超时则返回None
        """
        # 创建任务分配消息
        message = TaskAssignMessage(
            sender_id=self.node_id,
            task_id=task.task_id,
            task_type=task.task_type.value,
            name=task.name,
            description=task.description,
            parameters=task.parameters,
            required_skills=task.required_skills,
            timeout=task.timeout or timeout,
            priority=task.priority.value,
        )

        # 发送到目标节点
        subject = f"cluster.nodes.{target_node}.tasks"
        await self.nats_client.publish(subject, message.to_dict())

        logger.info(f"任务已发送到节点: {task.task_id} -> {target_node}")

        # 等待结果
        return await self._wait_for_result(task.task_id, timeout)

    async def broadcast_task(
        self,
        task: Task,
        timeout: int = 300,
    ) -> Optional[TaskResultMessage]:
        """
        广播任务到所有节点

        Args:
            task: 要广播的任务
            timeout: 超时时间（秒）

        Returns:
            任务结果，如果超时则返回None
        """
        # 创建任务分配消息
        message = TaskAssignMessage(
            sender_id=self.node_id,
            task_id=task.task_id,
            task_type=task.task_type.value,
            name=task.name,
            description=task.description,
            parameters=task.parameters,
            required_skills=task.required_skills,
            timeout=task.timeout or timeout,
            priority=task.priority.value,
        )

        # 广播任务
        subject = "cluster.tasks.broadcast"
        await self.nats_client.publish(subject, message.to_dict())

        logger.info(f"任务已广播: {task.task_id}")

        # 等待结果
        return await self._wait_for_result(task.task_id, timeout)

    async def _wait_for_result(
        self,
        task_id: str,
        timeout: int,
    ) -> Optional[TaskResultMessage]:
        """
        等待任务结果

        Args:
            task_id: 任务ID
            timeout: 超时时间（秒）

        Returns:
            任务结果，如果超时则返回None
        """
        # 创建Future
        future = asyncio.Future()
        self._pending_tasks[task_id] = future

        try:
            # 等待结果
            result = await asyncio.wait_for(future, timeout=timeout)
            return result

        except asyncio.TimeoutError:
            logger.warning(f"等待任务结果超时: {task_id}")
            return None

        finally:
            # 清理Future
            self._pending_tasks.pop(task_id, None)

    async def _send_result(
        self,
        task_id: str,
        success: bool,
        result: Any = None,
        error: str = None,
    ):
        """
        发送任务结果

        Args:
            task_id: 任务ID
            success: 是否成功
            result: 结果数据
            error: 错误信息
        """
        # 创建结果消息
        message = TaskResultMessage(
            sender_id=self.node_id,
            task_id=task_id,
            success=success,
            result=result,
            error=error,
            timestamp=datetime.now(),
        )

        # 发送结果
        subject = f"cluster.task.results.{task_id}"
        await self.nats_client.publish(subject, message.to_dict())

        logger.debug(f"任务结果已发送: {task_id} (成功: {success})")

    async def register_result_callback(
        self,
        task_id: str,
        callback: Callable[[TaskResultMessage], Awaitable[None]],
    ):
        """
        注册任务结果回调

        Args:
            task_id: 任务ID
            callback: 回调函数
        """
        self._result_callbacks[task_id] = callback

    async def send_heartbeat(
        self,
        cpu_usage: float = 0.0,
        memory_usage: float = 0.0,
        running_tasks: int = 0,
        available_skills: List[str] = None,
    ):
        """
        发送节点心跳

        Args:
            cpu_usage: CPU使用率
            memory_usage: 内存使用率
            running_tasks: 运行任务数
            available_skills: 可用技能列表
        """
        message = NodeHeartbeatMessage(
            sender_id=self.node_id,
            cpu_usage=cpu_usage,
            memory_usage=memory_usage,
            running_tasks=running_tasks,
            status="online",
            available_skills=available_skills or [],
            timestamp=datetime.now(),
        )

        # 发送心跳
        subject = "cluster.nodes.heartbeat"
        await self.nats_client.publish(subject, message.to_dict())

        logger.debug(f"心跳已发送: {self.node_id}")


class TaskRequestResponse:
    """
    任务请求-响应模式

    支持同步请求和响应模式
    """

    def __init__(
        self,
        nats_client: NATSClient,
        node_id: str,
        timeout: int = 30,
    ):
        """
        初始化请求-响应服务

        Args:
            nats_client: NATS客户端
            node_id: 当前节点ID
            timeout: 默认超时时间（秒）
        """
        self.nats_client = nats_client
        self.node_id = node_id
        self.timeout = timeout

        # 响应处理器
        self._response_handlers: Dict[str, Callable] = {}

        # 等待中的请求
        self._pending_requests: Dict[str, asyncio.Future] = {}

    async def start(self):
        """启动服务"""
        # 订阅响应主题
        subject = f"cluster.nodes.{self.node_id}.responses"
        await self.nats_client.subscribe(
            subject,
            self._handle_response,
        )
        logger.info(f"请求-响应服务已启动: {subject}")

    async def stop(self):
        """停止服务"""
        # 取消所有等待中的Future
        for future in self._pending_requests.values():
            if not future.done():
                future.cancel()

        logger.info("请求-响应服务已停止")

    async def request(
        self,
        target_node: str,
        action: str,
        data: Dict[str, Any] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        发送请求到指定节点

        Args:
            target_node: 目标节点ID
            action: 动作名称
            data: 请求数据

        Returns:
            响应数据，如果超时则返回None
        """
        # 创建请求ID
        request_id = str(uuid4())

        # 创建请求消息
        message = {
            "request_id": request_id,
            "sender_id": self.node_id,
            "action": action,
            "data": data or {},
            "timestamp": datetime.now().isoformat(),
        }

        # 创建Future等待响应
        future = asyncio.Future()
        self._pending_requests[request_id] = future

        try:
            # 发送请求
            subject = f"cluster.nodes.{target_node}.requests"
            await self.nats_client.publish(subject, message)

            logger.info(f"请求已发送: {request_id} -> {target_node} ({action})")

            # 等待响应
            response = await asyncio.wait_for(future, timeout=self.timeout)
            return response

        except asyncio.TimeoutError:
            logger.warning(f"请求超时: {request_id}")
            return None

        finally:
            # 清理Future
            self._pending_requests.pop(request_id, None)

    async def _handle_response(self, message: Dict[str, Any]):
        """
        处理响应消息

        Args:
            message: 响应消息
        """
        try:
            request_id = message.get("request_id")

            if not request_id:
                return

            # 触发等待中的Future
            future = self._pending_requests.get(request_id)
            if future and not future.done():
                future.set_result(message)

        except Exception as e:
            logger.error(f"处理响应消息失败: {e}", exc_info=True)

    def register_handler(self, action: str, handler: Callable):
        """
        注册请求处理器

        Args:
            action: 动作名称
            handler: 处理器函数
        """
        self._response_handlers[action] = handler
        logger.info(f"已注册请求处理器: {action}")
