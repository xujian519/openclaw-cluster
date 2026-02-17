"""
OpenClaw 集群系统 - 工作节点心跳模块

负责定期向协调器发送心跳，上报节点状态和系统信息
"""
import asyncio
import socket
import platform
import psutil
from typing import Optional, Dict, Any
from datetime import datetime

from common.logging import get_logger
from common.config import Config

logger = get_logger(__name__)


class HeartbeatClient:
    """
    心跳客户端

    定期向协调器发送心跳信息
    """

    def __init__(
        self,
        config: Config,
        coordinator_url: str,
        node_id: str,
        available_skills: list,
    ):
        """
        初始化心跳客户端

        Args:
            config: 配置对象
            coordinator_url: 协调器URL
            node_id: 节点ID
            available_skills: 可用技能列表
        """
        self.config = config
        self.coordinator_url = coordinator_url.rstrip("/")
        self.node_id = node_id
        self.available_skills = available_skills
        self.heartbeat_interval = config.worker.heartbeat_interval
        self.running = False
        self.heartbeat_task: Optional[asyncio.Task] = None
        self.registered = False

        # 系统信息缓存
        self.system_info = self._collect_system_info()

        logger.info(
            f"心跳客户端初始化完成 - 节点ID: {node_id}, "
            f"协调器: {coordinator_url}, "
            f"间隔: {self.heartbeat_interval}s"
        )

    async def start(self):
        """启动心跳客户端"""
        if self.running:
            logger.warning("心跳客户端已经在运行")
            return

        self.running = True

        # 先注册节点
        success = await self._register_node()
        if not success:
            logger.error("节点注册失败，无法启动心跳客户端")
            self.running = False
            return

        self.registered = True
        logger.info("节点注册成功，开始发送心跳")

        # 启动心跳任务
        self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def stop(self):
        """停止心跳客户端"""
        if not self.running:
            return

        logger.info("停止心跳客户端")
        self.running = False

        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass

        # 发送最后一次心跳通知节点关闭
        await self._notify_shutdown()

    async def send_heartbeat_now(self) -> bool:
        """
        立即发送一次心跳

        Returns:
            是否发送成功
        """
        try:
            return await self._send_heartbeat()
        except Exception as e:
            logger.error(f"发送心跳失败: {e}")
            return False

    def _collect_system_info(self) -> Dict[str, Any]:
        """
        收集系统信息

        Returns:
            系统信息字典
        """
        try:
            # 获取系统平台
            system = platform.system().lower()
            if system == "darwin":
                platform_name = "macos"
            elif system == "windows":
                platform_name = "windows"
            else:
                platform_name = "linux"

            # 获取架构
            machine = platform.machine().lower()
            if machine in ["x86_64", "amd64"]:
                arch = "x64"
            elif machine in ["arm64", "aarch64"]:
                arch = "arm64"
            elif machine.startswith("arm"):
                arch = "arm"
            else:
                arch = machine

            # 获取主机名
            hostname = socket.gethostname()

            # 获取IP地址
            ip_address = self._get_local_ip()

            return {
                "hostname": hostname,
                "platform": platform_name,
                "arch": arch,
                "ip_address": ip_address,
            }

        except Exception as e:
            logger.error(f"收集系统信息失败: {e}")
            return {
                "hostname": "unknown",
                "platform": "linux",
                "arch": "x64",
                "ip_address": "",
            }

    def _get_local_ip(self) -> str:
        """
        获取本地IP地址

        Returns:
            IP地址字符串
        """
        try:
            # 创建一个UDP socket来获取本地IP
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                # 不需要真正连接，只是为了获取本地IP
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
            return ip
        except Exception:
            return "127.0.0.1"

    def _get_resource_usage(self) -> Dict[str, float]:
        """
        获取资源使用情况

        Returns:
            资源使用情况字典
        """
        try:
            # CPU使用率
            cpu_usage = psutil.cpu_percent(interval=0.1)

            # 内存使用率
            memory = psutil.virtual_memory()
            memory_usage = memory.percent

            # 磁盘使用率
            disk = psutil.disk_usage("/")
            disk_usage = (disk.used / disk.total) * 100

            return {
                "cpu_usage": round(cpu_usage, 2),
                "memory_usage": round(memory_usage, 2),
                "disk_usage": round(disk_usage, 2),
            }

        except Exception as e:
            logger.warning(f"获取资源使用情况失败: {e}")
            return {
                "cpu_usage": 0.0,
                "memory_usage": 0.0,
                "disk_usage": 0.0,
            }

    async def _register_node(self) -> bool:
        """
        注册节点到协调器

        Returns:
            是否注册成功
        """
        import aiohttp
        import re

        try:
            # 将localhost替换为127.0.0.1以避免IPv6连接问题
            coordinator_url = re.sub(r'://localhost:', '://127.0.0.1:', self.coordinator_url)

            timeout = aiohttp.ClientTimeout(total=10, connect=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{coordinator_url}/api/v1/nodes/register",
                    json={
                        "hostname": self.system_info["hostname"],
                        "platform": self.system_info["platform"],
                        "arch": self.system_info["arch"],
                        "available_skills": self.available_skills,
                        "ip_address": self.system_info["ip_address"],
                        "max_concurrent_tasks": self.config.worker.max_concurrent_tasks,
                        "node_id": self.node_id,
                    },
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data["success"]:
                            logger.info(
                                f"节点注册成功: {data.get('node_id')} - "
                                f"{data.get('message')}"
                            )
                            return True
                        else:
                            logger.error(f"节点注册失败: {data.get('message')}")
                            return False
                    else:
                        text = await response.text()
                        logger.error(
                            f"节点注册请求失败: HTTP {response.status} - "
                            f"{text}"
                        )
                        return False

        except Exception as e:
            logger.error(f"节点注册时发生错误: {e}")
            return False

    async def _send_heartbeat(self) -> bool:
        """
        发送心跳到协调器

        Returns:
            是否发送成功
        """
        import aiohttp
        import re

        try:
            # 获取当前资源使用情况
            usage = self._get_resource_usage()

            # TODO: 获取实际运行的任务数
            running_tasks = 0

            # 将localhost替换为127.0.0.1以避免IPv6连接问题
            coordinator_url = re.sub(r'://localhost:', '://127.0.0.1:', self.coordinator_url)

            timeout = aiohttp.ClientTimeout(total=5, connect=3)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{coordinator_url}/api/v1/nodes/{self.node_id}/heartbeat",
                    json={
                        "cpu_usage": usage["cpu_usage"],
                        "memory_usage": usage["memory_usage"],
                        "disk_usage": usage["disk_usage"],
                        "running_tasks": running_tasks,
                    },
                ) as response:
                    if response.status == 200:
                        logger.debug(
                            f"心跳发送成功 - CPU: {usage['cpu_usage']}%, "
                            f"内存: {usage['memory_usage']}%, "
                            f"磁盘: {usage['disk_usage']}%"
                        )
                        return True
                    else:
                        text = await response.text()
                        logger.warning(
                            f"心跳发送失败: HTTP {response.status} - {text}"
                        )
                        return False

        except asyncio.TimeoutError:
            logger.warning("心跳发送超时")
            return False
        except Exception as e:
            logger.error(f"发送心跳时发生错误: {e}")
            return False

    async def _notify_shutdown(self):
        """通知协调器节点即将关闭"""
        import aiohttp
        import re

        try:
            # 将localhost替换为127.0.0.1以避免IPv6连接问题
            coordinator_url = re.sub(r'://localhost:', '://127.0.0.1:', self.coordinator_url)

            timeout = aiohttp.ClientTimeout(total=5, connect=3)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{coordinator_url}/api/v1/nodes/{self.node_id}/shutdown"
                ) as response:
                    if response.status == 200:
                        logger.info("已通知协调器节点关闭")
                    else:
                        logger.warning(f"通知节点关闭失败: HTTP {response.status}")

        except Exception as e:
            logger.error(f"通知节点关闭时发生错误: {e}")

    async def _heartbeat_loop(self):
        """心跳循环"""
        logger.info("心跳循环已启动")

        while self.running:
            try:
                # 发送心跳
                await self._send_heartbeat()

                # 等待下一次心跳
                await asyncio.sleep(self.heartbeat_interval)

            except asyncio.CancelledError:
                logger.info("心跳循环被取消")
                break
            except Exception as e:
                logger.error(f"心跳循环发生错误: {e}", exc_info=True)
                # 发生错误后等待一段时间再继续
                await asyncio.sleep(self.heartbeat_interval)


# 便捷函数


async def create_heartbeat_client(
    config: Config,
    coordinator_url: str,
    node_id: str,
    available_skills: list,
) -> HeartbeatClient:
    """
    创建心跳客户端

    Args:
        config: 配置对象
        coordinator_url: 协调器URL
        node_id: 节点ID
        available_skills: 可用技能列表

    Returns:
        心跳客户端实例
    """
    return HeartbeatClient(
        config=config,
        coordinator_url=coordinator_url,
        node_id=node_id,
        available_skills=available_skills,
    )
