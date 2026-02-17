"""
OpenClaw 集群系统 - 主节点

协调集群中的任务调度、状态管理和节点通信
"""
import asyncio
import signal
import socket
from typing import Optional
from pathlib import Path

from common.config import Config, load_config
from common.models import ClusterState, NodeInfo, NodeStatus, Task
from common.logging import get_logger, setup_logging
from communication.nats_client import NATSClient
from communication.messages import NodeHeartbeatMessage, TaskAssignMessage, TaskResultMessage

logger = get_logger(__name__)


class Coordinator:
    """集群协调器"""

    def __init__(self, config: Config):
        """
        初始化协调器

        Args:
            config: 配置对象
        """
        self.config = config
        self.node_id = config.node_id or f"coordinator_{socket.gethostname()}"
        self.cluster_state = ClusterState()
        self.nats_client: Optional[NATSClient] = None
        self.running = False

        # 设置日志
        setup_logging(
            level=config.logging.level,
            format_type=config.logging.format,
            output=config.logging.output,
        )

    async def start(self):
        """启动协调器"""
        logger.info(f"启动协调器: {self.node_id}")

        # 连接到 NATS
        self.nats_client = NATSClient(self.config.nats, self.node_id)
        if not await self.nats_client.connect():
            logger.error("连接 NATS 失败，无法启动")
            return

        # 订阅消息
        await self._setup_subscriptions()

        # 启动 API 服务
        # await self._start_api_server()

        self.running = True
        logger.info("协调器已启动")

        # 运行主循环
        await self._main_loop()

    async def stop(self):
        """停止协调器"""
        logger.info("停止协调器")
        self.running = False

        if self.nats_client:
            await self.nats_client.disconnect()

        logger.info("协调器已停止")

    async def _setup_subscriptions(self):
        """设置消息订阅"""
        # 节点心跳
        await self.nats_client.subscribe(
            "cluster.heartbeat",
            self._handle_heartbeat,
        )

        # 任务结果
        await self.nats_client.subscribe(
            "cluster.task.result",
            self._handle_task_result,
        )

        # 节点注册
        await self.nats_client.subscribe(
            "cluster.node.register",
            self._handle_node_register,
        )

    async def _handle_heartbeat(self, msg):
        """处理节点心跳"""
        try:
            import json
            data = json.loads(msg.data.decode())

            node_id = data.get("sender_id")
            if not node_id:
                return

            # 更新节点状态
            self.cluster_state.update_node_status(
                node_id,
                NodeStatus(data.get("status", "online"))
            )

            logger.debug(f"收到心跳: {node_id}")

        except Exception as e:
            logger.error(f"处理心跳时出错: {e}")

    async def _handle_task_result(self, msg):
        """处理任务结果"""
        try:
            import json
            data = json.loads(msg.data.decode())

            task_id = data.get("task_id")
            success = data.get("success", False)

            logger.info(f"任务 {task_id} {'完成' if success else '失败'}")

            # 更新任务状态
            if task_id in self.cluster_state.tasks:
                task = self.cluster_state.tasks[task_id]
                if success:
                    task.result = data.get("result")
                    task.status = TaskStatus.COMPLETED
                else:
                    task.error = data.get("error")
                    task.status = TaskStatus.FAILED

                self.cluster_state.version += 1

        except Exception as e:
            logger.error(f"处理任务结果时出错: {e}")

    async def _handle_node_register(self, msg):
        """处理节点注册"""
        try:
            import json
            data = json.loads(msg.data.decode())

            node_info = NodeInfo(**data)
            self.cluster_state.add_node(node_info)

            logger.info(f"节点注册: {node_info.node_id}")

        except Exception as e:
            logger.error(f"处理节点注册时出错: {e}")

    async def _main_loop(self):
        """主循环"""
        while self.running:
            # 定期检查节点健康状态
            await self._check_node_health()

            # 等待一段时间
            await asyncio.sleep(30)

    async def _check_node_health(self):
        """检查节点健康状态"""
        from datetime import datetime, timedelta

        timeout = timedelta(seconds=90)  # 90秒心跳超时

        for node_id, node in list(self.cluster_state.nodes.items()):
            if node.last_heartbeat:
                if datetime.now() - node.last_heartbeat > timeout:
                    logger.warning(f"节点 {node_id} 心跳超时")
                    self.cluster_state.update_node_status(node_id, NodeStatus.OFFLINE)


async def create_coordinator(config_path: str) -> Coordinator:
    """
    创建协调器

    Args:
        config_path: 配置文件路径

    Returns:
        协调器实例
    """
    config = load_config(config_path)
    return Coordinator(config)


async def main():
    """主函数"""
    import sys

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config/coordinator.yaml"

    coordinator = await create_coordinator(config_path)

    # 设置信号处理
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def signal_handler():
        logger.info("收到停止信号")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        # 启动协调器
        await coordinator.start()

        # 等待停止信号
        await stop_event.wait()

    finally:
        # 停止协调器
        await coordinator.stop()


if __name__ == "__main__":
    asyncio.run(main())
