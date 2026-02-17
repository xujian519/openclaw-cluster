"""
OpenClaw 集群系统 - 工作节点服务
"""

import asyncio
import platform
import re
import socket
from collections.abc import Awaitable
from typing import Any, Callable, Dict, Optional

import psutil

from common.config import Config
from common.http_client import close_session, get_session
from common.logging import get_logger
from common.models import NodeInfo, NodeStatus
from communication.messages import TaskAssignMessage
from communication.nats_client import NATSClient
from communication.task_messaging import TaskMessaging
from skills.skill_discovery import BUILTIN_SKILLS, SkillDiscovery
from skills.skill_registry import SkillRegistry
from worker.heartbeat import HeartbeatClient

logger = get_logger(__name__)


class WorkerService:
    """
    工作节点服务

    处理任务执行、心跳上报和节点管理
    """

    def __init__(
        self,
        config: Config,
        node_id: Optional[str] = None,
    ):
        """
        初始化工作节点服务

        Args:
            config: 配置对象
            node_id: 节点ID（可选，自动生成）
        """
        self.config = config

        # 节点信息
        self.node_id = node_id or self._generate_node_id()
        self.hostname = socket.gethostname()
        # 平台名称标准化：darwin -> macos
        raw_platform = platform.system().lower()
        self.platform = {
            "darwin": "macos",
            "windows": "windows",
            "linux": "linux",
        }.get(raw_platform, raw_platform)
        self.arch = platform.machine().lower()

        # 获取IP地址
        try:
            self.ip_address = socket.gethostbyname(self.hostname)
        except Exception:
            self.ip_address = "127.0.0.1"

        # 获取Tailscale IP（如果可用）
        self.tailscale_ip = self._get_tailscale_ip()

        # 监听端口
        self.port = getattr(config.worker, "port", 18789)

        # 最大并发任务数
        self.max_concurrent_tasks = getattr(config.worker, "max_concurrent_tasks", 5)

        # 消息通信
        self.nats_client: Optional[NATSClient] = None
        self.task_messaging: Optional[TaskMessaging] = None

        # 心跳客户端
        self.heartbeat_client: Optional[HeartbeatClient] = None

        # 技能系统
        self.skill_registry: Optional[SkillRegistry] = None
        self.skill_discovery: Optional[SkillDiscovery] = None

        # 任务处理器 (task_type -> handler)
        self._task_handlers: Dict[str, Callable] = {}

        # 运行状态
        self._is_running = False
        self._running_tasks: Dict[str, asyncio.Task] = {}

        # 协调器地址
        coordinator_host = getattr(config.coordinator, "host", "localhost")
        coordinator_port = getattr(config.coordinator, "port", 8888)
        self.coordinator_url = f"http://{coordinator_host}:{coordinator_port}"

    def _generate_node_id(self) -> str:
        """生成节点ID"""
        # 使用主机名作为基础
        base_id = socket.gethostname().lower().replace(".", "_")
        # 添加平台标识
        platform_id = platform.system().lower()[:3]
        return f"{platform_id}_{base_id}"

    def _get_tailscale_ip(self) -> Optional[str]:
        """获取Tailscale IP地址"""
        try:
            # 尝试读取Tailscale配置
            import subprocess

            result = subprocess.run(
                ["tailscale", "ip", "-4"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
        return None

    async def start(self):
        """启动工作节点服务"""
        if self._is_running:
            logger.warning("工作节点服务已在运行")
            return

        logger.info(f"正在启动工作节点服务: {self.node_id}")

        try:
            # 1. 初始化技能系统
            await self._initialize_skills()

            # 2. 初始化消息通信
            await self._initialize_messaging()

            # 3. 初始化心跳客户端
            await self._initialize_heartbeat()

            # 4. 注册到协调器
            await self._register_to_coordinator()

            # 5. 启动后台任务
            self._start_background_tasks()

            self._is_running = True

            logger.info(f"✅ 工作节点服务启动完成: {self.node_id}")

        except Exception as e:
            logger.error(f"工作节点服务启动失败: {e}", exc_info=True)
            await self.stop()
            raise

    async def stop(self):
        """停止工作节点服务"""
        if not self._is_running:
            return

        logger.info(f"正在停止工作节点服务: {self.node_id}")

        try:
            # 取消所有运行中的任务
            for task_id, task in list(self._running_tasks.items()):
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            # 停止心跳
            if self.heartbeat_client:
                await self.heartbeat_client.stop()

            # 停止消息服务
            if self.task_messaging:
                await self.task_messaging.stop()

            # 停止技能发现
            if self.skill_discovery:
                await self.skill_discovery.stop()

            if self.nats_client:
                await self.nats_client.close()

            await close_session()

            self._is_running = False

            logger.info(f"✅ 工作节点服务已停止: {self.node_id}")

        except Exception as e:
            logger.error(f"停止工作节点服务时出错: {e}", exc_info=True)

    async def _initialize_skills(self):
        """初始化技能系统"""
        logger.info("初始化技能系统...")

        # 创建技能注册表
        # 注意：工作节点不需要状态管理器，使用简单的内存注册表
        from skills.skill_registry import SkillRegistry
        from storage.database import Database
        from storage.state_manager import StateManager

        # 创建临时内存数据库
        db = Database(":memory:")
        await db.initialize()
        state_manager = StateManager(db)
        await state_manager.initialize()

        self.skill_registry = SkillRegistry(state_manager)

        # 创建技能发现服务
        skills_dir = getattr(self.config.worker, "skills_dir", "./skills")
        self.skill_discovery = SkillDiscovery(
            self.skill_registry,
            skills_dir=skills_dir,
            discovery_interval=60,
        )

        # 注册内置技能
        await self.skill_discovery.register_local_skills(BUILTIN_SKILLS)

        # 启动技能发现
        await self.skill_discovery.start(self.node_id)

        # 获取可用技能
        skills = await self.skill_discovery.get_discovered_skills()
        available_skills = [s.name for s in skills]

        logger.info(f"✅ 技能系统初始化完成，可用技能: {available_skills}")

    async def _initialize_messaging(self):
        """初始化消息通信"""
        logger.info("初始化消息通信...")

        try:
            # 创建NATS配置
            from communication.nats_client import NATSConfig

            nats_url = getattr(self.config.communication, "nats_url", "nats://localhost:4222")

            nats_config = NATSConfig(
                url=nats_url,
                max_reconnect=10,
            )

            # 创建NATS客户端
            self.nats_client = NATSClient(nats_config)

            # 连接NATS
            if await self.nats_client.connect():
                logger.info("✅ NATS连接成功")
            else:
                logger.warning("NATS连接失败，将使用HTTP通信")

            # 创建任务消息服务
            if self.nats_client and self.nats_client.is_connected:
                self.task_messaging = TaskMessaging(
                    self.nats_client,
                    node_id=self.node_id,
                )

                # 注册任务处理器
                await self._register_task_handlers()

                # 启动消息服务
                await self.task_messaging.start()

                logger.info("✅ 消息通信初始化完成")
        except Exception as e:
            logger.warning(f"消息通信初始化失败: {e}")

    async def _initialize_heartbeat(self):
        """初始化心跳客户端"""
        logger.info("初始化心跳客户端...")

        available_skills = list(self.skill_registry._skills.keys())

        self.heartbeat_client = HeartbeatClient(
            config=self.config,
            coordinator_url=self.coordinator_url,
            node_id=self.node_id,
            available_skills=available_skills,
            get_running_tasks=lambda: len(self._running_tasks),
        )

        logger.info(f"✅ 心跳客户端初始化完成 (技能: {available_skills})")

    async def _register_to_coordinator(self):
        """注册到协调器"""
        logger.info("注册到协调器...")

        # 获取可用技能 - 直接从skill_registry获取
        available_skills = []
        if self.skill_registry:
            available_skills = list(self.skill_registry._skills.keys())
            logger.info(f"从技能注册表获取到技能: {available_skills}")

        # 创建节点信息
        node_info = NodeInfo(
            node_id=self.node_id,
            hostname=self.hostname,
            platform=self.platform,
            arch=self.arch,
            status=NodeStatus.ONLINE,
            available_skills=available_skills,
            ip_address=self.ip_address,
            tailscale_ip=self.tailscale_ip,
            port=self.port,
            max_concurrent_tasks=self.max_concurrent_tasks,
            running_tasks=0,
        )

        # 通过HTTP注册
        try:
            payload = {
                "hostname": node_info.hostname,
                "platform": node_info.platform,
                "arch": node_info.arch,
                "available_skills": node_info.available_skills,
                "ip_address": node_info.ip_address,
                "tailscale_ip": node_info.tailscale_ip,
                "port": node_info.port,
                "max_concurrent_tasks": node_info.max_concurrent_tasks,
            }

            coordinator_url = re.sub(r"://localhost:", "://127.0.0.1:", self.coordinator_url)
            logger.info(f"正在注册节点 {node_info.node_id} 到协调器 {coordinator_url}")

            session = await get_session()
            async with session.post(
                f"{coordinator_url}/api/v1/nodes/register",
                json=payload,
            ) as response:
                logger.info(f"注册响应: 状态码={response.status}")

                if response.status == 200:
                    result = await response.json()
                    returned_node_id = result.get("node_id")
                    if returned_node_id and returned_node_id != self.node_id:
                        logger.info(f"节点ID已更新: {self.node_id} -> {returned_node_id}")
                        self.node_id = returned_node_id
                        if self.heartbeat_client:
                            self.heartbeat_client.node_id = returned_node_id
                    logger.info(f"✅ 成功注册到协调器: {returned_node_id}")
                else:
                    text = await response.text()
                    logger.warning(f"注册到协调器失败: {response.status} - {text[:200]}")
        except Exception as e:
            logger.error(f"注册请求异常: {e}", exc_info=True)

    async def _register_task_handlers(self):
        """注册任务处理器"""
        # 注册示例任务处理器
        await self.task_messaging.register_task_handler(
            "interactive",
            self._handle_interactive_task,
        )

        await self.task_messaging.register_task_handler(
            "batch",
            self._handle_batch_task,
        )

        logger.info("任务处理器已注册")

    async def _handle_interactive_task(self, message: TaskAssignMessage) -> Dict[str, Any]:
        """
        处理交互式任务

        Args:
            message: 任务分配消息

        Returns:
            任务结果
        """
        logger.info(f"执行交互式任务: {message.task_id}")

        # 模拟任务执行
        await asyncio.sleep(1)

        # 返回结果
        return {
            "status": "completed",
            "result": f"任务 {message.task_id} 执行完成",
            "data": {
                "task_type": "interactive",
                "execution_time": 1.0,
            },
        }

    async def _handle_batch_task(self, message: TaskAssignMessage) -> Dict[str, Any]:
        """
        处理批处理任务

        Args:
            message: 任务分配消息

        Returns:
            任务结果
        """
        logger.info(f"执行批处理任务: {message.task_id}")

        # 模拟任务执行
        await asyncio.sleep(2)

        # 返回结果
        return {
            "status": "completed",
            "result": f"批处理任务 {message.task_id} 执行完成",
            "data": {
                "task_type": "batch",
                "processed_items": 100,
                "execution_time": 2.0,
            },
        }

    def _start_background_tasks(self):
        """启动后台任务"""
        # 启动心跳
        if self.heartbeat_client:
            asyncio.create_task(self.heartbeat_client.start())

        logger.info("后台任务已启动")

    async def register_task_handler(
        self,
        task_type: str,
        handler: Callable[[TaskAssignMessage], Awaitable[Dict[str, Any]]],
    ):
        """
        注册自定义任务处理器

        Args:
            task_type: 任务类型
            handler: 处理器函数
        """
        self._task_handlers[task_type] = handler

        # 如果消息服务已启动，注册到消息服务
        if self.task_messaging:
            await self.task_messaging.register_task_handler(
                task_type,
                handler,
            )

        logger.info(f"自定义任务处理器已注册: {task_type}")

    async def get_system_metrics(self) -> Dict[str, float]:
        """
        获取系统指标

        Returns:
            系统指标字典
        """
        # CPU使用率
        cpu_usage = psutil.cpu_percent(interval=1)

        # 内存使用率
        memory = psutil.virtual_memory()
        memory_usage = memory.percent

        # 磁盘使用率
        disk = psutil.disk_usage("/")
        disk_usage = disk.percent

        # 运行任务数
        running_tasks = len(self._running_tasks)

        return {
            "cpu_usage": cpu_usage,
            "memory_usage": memory_usage,
            "disk_usage": disk_usage,
            "running_tasks": running_tasks,
        }

    async def get_available_skills(self) -> list:
        """
        获取可用技能列表

        Returns:
            技能名称列表
        """
        if not self.skill_discovery:
            return []

        skills = await self.skill_discovery.get_discovered_skills()
        return [s.name for s in skills]


async def create_worker(
    config: Config,
    node_id: Optional[str] = None,
) -> WorkerService:
    """
    创建工作节点服务

    Args:
        config: 配置对象
        node_id: 节点ID（可选）

    Returns:
        工作节点服务实例
    """
    worker = WorkerService(config, node_id)
    await worker.start()
    return worker
