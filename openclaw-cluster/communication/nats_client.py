"""
OpenClaw 集群系统 - NATS 客户端

提供 NATS 连接和消息通信功能
"""

import asyncio
from typing import Callable, Optional

import nats
from nats.errors import NoServersError, TimeoutError

from common.config import NATSConfig
from common.logging import get_logger

logger = get_logger(__name__)


class NATSClient:
    """NATS 客户端封装"""

    def __init__(
        self,
        config: NATSConfig,
        node_id: Optional[str] = None,
    ):
        """
        初始化 NATS 客户端

        Args:
            config: NATS 配置
            node_id: 节点ID
        """
        self.config = config
        self.node_id = node_id or "unknown"
        self.nc: Optional[nats.NATS] = None
        self.js = None
        self._connected = False
        self._subscriptions = []

    async def connect(self) -> bool:
        """
        连接到 NATS 服务器

        Returns:
            连接是否成功
        """
        try:
            logger.info(f"连接到 NATS: {self.config.url}")
            self.nc = await nats.connect(
                servers=[self.config.url],
                max_reconnect_attempts=self.config.max_reconnect,
                reconnect_time_wait=self.config.reconnect_wait,
                disconnected_cb=self._on_disconnected,
                reconnected_cb=self._on_reconnected,
                error_cb=self._on_error,
                closed_cb=self._on_closed,
            )

            # 创建 JetStream 上下文
            if self.config.jetstream_enabled:
                self.js = self.nc.jetstream()
                logger.info("JetStream 已启用")

            self._connected = True
            logger.info(f"成功连接到 NATS: {self.config.url}")
            return True

        except NoServersError as e:
            logger.error(f"无法连接到 NATS 服务器: {e}")
            return False
        except Exception as e:
            logger.error(f"连接 NATS 时发生错误: {e}")
            return False

    async def disconnect(self):
        """断开连接"""
        # 取消所有订阅任务
        for task in self._subscriptions:
            if isinstance(task, asyncio.Task):
                task.cancel()

        # 等待任务取消完成
        if self._subscriptions:
            await asyncio.gather(*self._subscriptions, return_exceptions=True)

        self._subscriptions.clear()

        # 关闭连接
        if self.nc:
            try:
                await self.nc.close()
            except Exception as e:
                logger.warning(f"关闭 NATS 连接时出错: {e}")

            self._connected = False
            logger.info("已断开 NATS 连接")

    async def publish(
        self,
        subject: str,
        payload: bytes,
    ) -> bool:
        """
        发布消息

        Args:
            subject: 主题
            payload: 消息内容

        Returns:
            是否发布成功
        """
        if not self._connected or not self.nc:
            logger.error("未连接到 NATS")
            return False

        try:
            await self.nc.publish(subject, payload)
            logger.debug(f"发布消息到 {subject}")
            return True
        except Exception as e:
            logger.error(f"发布消息到 {subject} 时出错: {e}")
            return False

    async def request(
        self,
        subject: str,
        payload: bytes,
        timeout: float = 5.0,
    ) -> Optional[bytes]:
        """
        发送请求并等待响应

        Args:
            subject: 主题
            payload: 请求内容
            timeout: 超时时间

        Returns:
            响应内容或 None
        """
        if not self._connected or not self.nc:
            logger.error("未连接到 NATS")
            return None

        try:
            response = await self.nc.request(subject, payload, timeout=timeout)
            logger.debug(f"请求 {subject} 收到响应")
            return response.data
        except TimeoutError:
            logger.warning(f"请求 {subject} 超时")
            return None
        except Exception as e:
            logger.error(f"请求 {subject} 时出错: {e}")
            return None

    async def subscribe(
        self,
        subject: str,
        handler: Callable,
        queue_group: Optional[str] = None,
    ):
        """
        订阅主题

        Args:
            subject: 主题
            handler: 消息处理函数
            queue_group: 队列组名

        Returns:
            订阅任务（用于取消订阅）
        """
        if not self._connected or not self.nc:
            logger.error("未连接到 NATS")
            return None

        async def message_handler():
            try:
                if queue_group:
                    sub = await self.nc.subscribe(subject, queue=queue_group)
                else:
                    sub = await self.nc.subscribe(subject)

                logger.info(
                    f"订阅主题: {subject}" + (f" (队列: {queue_group})" if queue_group else "")
                )

                async for msg in sub.messages:
                    try:
                        await handler(msg)
                    except Exception as e:
                        logger.error(f"处理消息时出错: {e}")

            except asyncio.CancelledError:
                logger.debug(f"订阅任务已取消: {subject}")
                raise
            except Exception as e:
                logger.error(f"订阅 {subject} 时出错: {e}")

        # 启动消息处理器任务
        task = asyncio.create_task(message_handler())
        self._subscriptions.append(task)
        return task

    async def unsubscribe(self, task):
        """
        取消订阅

        Args:
            task: 订阅任务
        """
        if task in self._subscriptions:
            task.cancel()
            self._subscriptions.remove(task)
            logger.debug("已取消订阅")

    def is_connected(self) -> bool:
        """是否已连接"""
        return self._connected

    # 回调函数
    async def _on_disconnected(self):
        """连接断开回调"""
        logger.warning("NATS 连接已断开")
        self._connected = False

    async def _on_reconnected(self):
        """重新连接回调"""
        logger.info("NATS 已重新连接")
        self._connected = True

    async def _on_error(self, error):
        """错误回调"""
        logger.error(f"NATS 错误: {error}")

    async def _on_closed(self):
        """连接关闭回调"""
        logger.info("NATS 连接已关闭")
        self._connected = False
