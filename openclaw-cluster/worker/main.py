"""
OpenClaw 集群系统 - 工作节点

执行任务、调用技能、上报结果
"""

import asyncio
import platform
import signal
import socket
from datetime import datetime
from typing import Any, Dict, Optional

from common.config import Config, load_config
from common.logging import get_logger, setup_logging
from common.models import NodeInfo, NodeStatus
from communication.messages import NodeHeartbeatMessage, TaskResultMessage
from communication.nats_client import NATSClient

logger = get_logger(__name__)


class Worker:
    """工作节点"""

    def __init__(self, config: Config):
        """
        初始化工作节点

        Args:
            config: 配置对象
        """
        self.config = config
        self.node_id = config.node_id or f"worker_{socket.gethostname()}_{config.worker.port}"
        self.nats_client: Optional[NATSClient] = None
        self.running = False
        self.running_tasks: Dict[str, asyncio.Task] = {}

        # 节点信息
        self.node_info = NodeInfo(
            node_id=self.node_id,
            hostname=socket.gethostname(),
            platform=platform.system().lower(),
            arch=platform.machine().lower(),
            status=NodeStatus.OFFLINE,
            tailscale_ip=self._get_tailscale_ip(),
            port=config.worker.port,
            max_concurrent_tasks=config.worker.max_concurrent_tasks,
        )

        # 设置日志
        setup_logging(
            level=config.logging.level,
            format_type=config.logging.format,
            output=config.logging.output,
        )

    def _get_tailscale_ip(self) -> str:
        """获取 Tailscale IP"""
        try:
            import subprocess

            result = subprocess.run(
                ["tailscale", "ip", "-4"],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except Exception:
            return ""

    async def start(self):
        """启动工作节点"""
        logger.info(f"启动工作节点: {self.node_id}")

        # 连接到 NATS
        self.nats_client = NATSClient(self.config.nats, self.node_id)
        if not await self.nats_client.connect():
            logger.error("连接 NATS 失败，无法启动")
            return

        # 注册节点
        await self._register_node()

        # 订阅消息
        await self._setup_subscriptions()

        # 启动心跳
        asyncio.create_task(self._heartbeat_loop())

        self.running = True
        logger.info("工作节点已启动")

        # 运行主循环
        await self._main_loop()

    async def stop(self):
        """停止工作节点"""
        logger.info("停止工作节点")
        self.running = False

        # 取消所有运行中的任务
        for task_id, task in self.running_tasks.items():
            task.cancel()
            logger.info(f"取消任务: {task_id}")

        # 注销节点
        await self._unregister_node()

        if self.nats_client:
            await self.nats_client.disconnect()

        logger.info("工作节点已停止")

    async def _register_node(self):
        """注册节点"""
        import json

        self.node_info.status = NodeStatus.ONLINE
        self.node_info.registered_at = datetime.now()

        # 发送注册信息
        message = json.dumps(
            {
                "node_id": self.node_info.node_id,
                "hostname": self.node_info.hostname,
                "platform": self.node_info.platform,
                "arch": self.node_info.arch,
                "ip_address": self.node_info.ip_address,
                "tailscale_ip": self.node_info.tailscale_ip,
                "port": self.node_info.port,
                "max_concurrent_tasks": self.node_info.max_concurrent_tasks,
                "available_skills": ["weather", "search"],  # 示例技能
                "tags": ["mac", "development"],
            }
        )

        await self.nats_client.publish("cluster.node.register", message.encode())
        logger.info(f"节点注册成功: {self.node_id}")

    async def _unregister_node(self):
        """注销节点"""
        self.node_info.status = NodeStatus.OFFLINE
        logger.info(f"节点注销: {self.node_id}")

    async def _setup_subscriptions(self):
        """设置消息订阅"""
        # 任务分配
        await self.nats_client.subscribe(
            "cluster.task.assign",
            self._handle_task_assign,
        )

    async def _handle_task_assign(self, msg):
        """处理任务分配"""
        try:
            import json

            data = json.loads(msg.data.decode())

            task_id = data.get("task_id")
            required_skills = data.get("required_skills", [])

            logger.info(f"收到任务: {task_id}, 需要技能: {required_skills}")

            # 检查是否有可用槽位
            if len(self.running_tasks) >= self.node_info.max_concurrent_tasks:
                logger.warning(f"任务队列已满，拒绝任务: {task_id}")
                return

            # 创建任务
            task = asyncio.create_task(self._execute_task(data))
            self.running_tasks[task_id] = task

        except Exception as e:
            logger.error(f"处理任务分配时出错: {e}")

    async def _execute_task(self, task_data: Dict[str, Any]):
        """执行任务"""
        task_id = task_data.get("task_id")
        logger.info(f"开始执行任务: {task_id}")

        try:
            # 模拟任务执行
            await asyncio.sleep(1)

            # 发送成功结果
            result_message = TaskResultMessage.create(
                sender_id=self.node_id,
                task_id=task_id,
                success=True,
                result={"message": "任务执行成功"},
                execution_time=1.0,
            )

            await self.nats_client.publish(
                "cluster.task.result",
                result_message.to_json().encode(),
            )

            logger.info(f"任务完成: {task_id}")

        except Exception as e:
            # 发送失败结果
            result_message = TaskResultMessage.create(
                sender_id=self.node_id,
                task_id=task_id,
                success=False,
                error=str(e),
            )

            await self.nats_client.publish(
                "cluster.task.result",
                result_message.to_json().encode(),
            )

            logger.error(f"任务失败: {task_id}, 错误: {e}")

        finally:
            # 移除任务
            if task_id in self.running_tasks:
                del self.running_tasks[task_id]

    async def _heartbeat_loop(self):
        """心跳循环"""
        while self.running:
            try:
                # 获取系统信息
                import psutil

                cpu_usage = psutil.cpu_percent()
                memory_usage = psutil.virtual_memory().percent

                # 更新节点信息
                self.node_info.cpu_usage = cpu_usage
                self.node_info.memory_usage = memory_usage
                self.node_info.running_tasks = len(self.running_tasks)
                self.node_info.last_heartbeat = datetime.now()

                # 发送心跳
                heartbeat = NodeHeartbeatMessage.create(
                    sender_id=self.node_id,
                    cpu_usage=cpu_usage,
                    memory_usage=memory_usage,
                    running_tasks=len(self.running_tasks),
                    status=self.node_info.status.value,
                )

                await self.nats_client.publish(
                    "cluster.heartbeat",
                    heartbeat.to_json().encode(),
                )

                logger.debug(f"心跳发送: {self.node_id}")

            except Exception as e:
                logger.error(f"发送心跳时出错: {e}")

            # 等待下一次心跳
            await asyncio.sleep(self.config.worker.heartbeat_interval)

    async def _main_loop(self):
        """主循环"""
        while self.running:
            await asyncio.sleep(1)


async def create_worker(config_path: str) -> Worker:
    """
    创建工作节点

    Args:
        config_path: 配置文件路径

    Returns:
        工作节点实例
    """
    config = load_config(config_path)
    return Worker(config)


async def main():
    """主函数"""
    import sys

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config/worker.yaml"

    worker = await create_worker(config_path)

    # 设置信号处理
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def signal_handler():
        logger.info("收到停止信号")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        # 启动工作节点
        await worker.start()

        # 等待停止信号
        await stop_event.wait()

    finally:
        # 停止工作节点
        await worker.stop()


if __name__ == "__main__":
    asyncio.run(main())
