"""
OpenClaw 集群系统 - 协调器服务

整合所有协调器组件的主服务
"""
import asyncio
from typing import Optional, Dict, Any
from pathlib import Path

from common.models import Task, TaskType
from common.logging import get_logger
from common.config import Config
from storage.database import Database
from storage.state_manager import StateManager
from coordinator.node_service import NodeRegistrationService
from coordinator.heartbeat_monitor import HeartbeatMonitor
from coordinator.api import create_api_app, APIServer
from skills.skill_registry import SkillRegistry
from skills.skill_discovery import SkillDiscovery, BUILTIN_SKILLS
from scheduler.task_scheduler import TaskScheduler, SchedulingStrategy
from communication.nats_client import NATSClient
from communication.task_messaging import TaskMessaging
from worker.heartbeat import HeartbeatClient

logger = get_logger(__name__)


class CoordinatorService:
    """
    协调器服务

    整合所有协调器组件，提供统一的集群管理服务
    """

    def __init__(self, config: Config):
        """
        初始化协调器服务

        Args:
            config: 配置对象
        """
        self.config = config

        # 存储层
        self.db: Optional[Database] = None
        self.state_manager: Optional[StateManager] = None

        # 节点管理
        self.node_service: Optional[NodeRegistrationService] = None
        self.heartbeat_monitor: Optional[HeartbeatMonitor] = None

        # 技能系统
        self.skill_registry: Optional[SkillRegistry] = None
        self.skill_discovery: Optional[SkillDiscovery] = None

        # 任务调度
        self.task_scheduler: Optional[TaskScheduler] = None

        # 消息通信
        self.nats_client: Optional[NATSClient] = None
        self.task_messaging: Optional[TaskMessaging] = None

        # API服务
        self.api_app = None

        # 运行状态
        self._is_running = False
        self._server = None

    async def start(self):
        """启动协调器服务"""
        if self._is_running:
            logger.warning("协调器服务已在运行")
            return

        logger.info("正在启动协调器服务...")

        try:
            # 1. 初始化存储层
            await self._initialize_storage()

            # 2. 初始化技能系统
            await self._initialize_skills()

            # 3. 初始化节点管理
            await self._initialize_node_management()

            # 4. 初始化任务调度
            await self._initialize_task_scheduling()

            # 5. 初始化消息通信
            await self._initialize_messaging()

            # 6. 初始化API服务
            await self._initialize_api()

            self._is_running = True

            logger.info("✅ 协调器服务启动完成")

        except Exception as e:
            logger.error(f"协调器服务启动失败: {e}", exc_info=True)
            await self.stop()
            raise

    async def stop(self):
        """停止协调器服务"""
        if not self._is_running:
            return

        logger.info("正在停止协调器服务...")

        try:
            # 停止API服务
            if self.api_server:
                await self.api_server.stop()
                self.api_server = None

            # 停止消息通信
            if self.task_messaging:
                await self.task_messaging.stop()

            # 停止任务调度
            if self.task_scheduler:
                await self.task_scheduler.stop()

            # 停止心跳监控
            if self.heartbeat_monitor:
                await self.heartbeat_monitor.stop()

            # 停止技能发现
            if self.skill_discovery:
                await self.skill_discovery.stop()

            # 关闭NATS连接
            if self.nats_client:
                await self.nats_client.close()

            # 关闭状态管理器
            if self.state_manager:
                await self.state_manager.shutdown()

            # 关闭数据库
            if self.db:
                await self.db.close()

            self._is_running = False

            logger.info("✅ 协调器服务已停止")

        except Exception as e:
            logger.error(f"停止协调器服务时出错: {e}", exc_info=True)

    async def _initialize_storage(self):
        """初始化存储层"""
        logger.info("初始化存储层...")

        # 创建数据库
        self.db = Database(self.config.storage.path)
        await self.db.initialize()

        # 创建状态管理器
        self.state_manager = StateManager(self.db)
        await self.state_manager.initialize()

        logger.info("✅ 存储层初始化完成")

    async def _initialize_skills(self):
        """初始化技能系统"""
        logger.info("初始化技能系统...")

        # 创建技能注册表
        self.skill_registry = SkillRegistry(self.state_manager)

        # 创建技能发现服务
        self.skill_discovery = SkillDiscovery(
            self.skill_registry,
            skills_dir=getattr(self.config.worker, 'skills_dir', './skills'),
            discovery_interval=60,
        )

        # 注册内置技能
        await self.skill_discovery.register_local_skills(BUILTIN_SKILLS)

        # 启动技能发现
        await self.skill_discovery.start("coordinator")

        logger.info("✅ 技能系统初始化完成")

    async def _initialize_node_management(self):
        """初始化节点管理"""
        logger.info("初始化节点管理...")

        # 创建节点注册服务
        self.node_service = NodeRegistrationService(self.db)

        # 创建心跳监控服务
        heartbeat_timeout = getattr(
            self.config.coordinator, 'heartbeat_timeout', 90
        )
        check_interval = getattr(
            self.config.coordinator, 'heartbeat_check_interval', 30
        )

        self.heartbeat_monitor = HeartbeatMonitor(
            self.db,
            heartbeat_timeout=heartbeat_timeout,
            check_interval=check_interval,
        )

        # 启动心跳监控
        await self.heartbeat_monitor.start()

        logger.info("✅ 节点管理初始化完成")

    async def _initialize_task_scheduling(self):
        """初始化任务调度"""
        logger.info("初始化任务调度...")

        # 创建任务调度器
        strategy = SchedulingStrategy.LEAST_TASKS
        scheduling_interval = 1

        self.task_scheduler = TaskScheduler(
            self.state_manager,
            strategy=strategy,
            scheduling_interval=scheduling_interval,
        )

        # 启动调度器
        await self.task_scheduler.start()

        logger.info("✅ 任务调度初始化完成")

    async def _initialize_messaging(self):
        """初始化消息通信"""
        logger.info("初始化消息通信...")

        try:
            # 创建NATS配置
            from common.config import NATSConfig

            nats_url = getattr(
                self.config.communication, 'nats_url', 'nats://localhost:4222'
            )

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
                logger.warning("NATS连接失败，消息功能将不可用")

            # 创建任务消息服务
            if self.nats_client.is_connected:
                self.task_messaging = TaskMessaging(
                    self.nats_client,
                    node_id="coordinator",
                )

                # 注册任务处理器
                await self._register_task_handlers()

                # 启动消息服务
                await self.task_messaging.start()

                logger.info("✅ 消息通信初始化完成")
        except Exception as e:
            logger.warning(f"消息通信初始化失败: {e}")

    async def _register_task_handlers(self):
        """注册任务处理器"""
        # 这里可以注册协调器需要处理的任务类型
        # 例如：集群管理任务、统计任务等
        pass

    async def _initialize_api(self):
        """初始化API服务"""
        logger.info("初始化API服务...")

        # 创建API服务器
        self.api_server = APIServer(
            config=self.config,
            node_service=self.node_service,
            heartbeat_monitor=self.heartbeat_monitor,
        )

        # 启动API服务器（在后台任务中运行）
        asyncio.create_task(self.api_server.start())

        # 等待API服务器启动
        await asyncio.sleep(1)

        logger.info("✅ API服务初始化完成")

    async def submit_task(self, task: Task) -> bool:
        """
        提交任务到调度器

        Args:
            task: 要提交的任务

        Returns:
            是否成功提交
        """
        if not self.task_scheduler:
            logger.error("任务调度器未初始化")
            return False

        return await self.task_scheduler.submit_task(task)

    async def get_cluster_status(self) -> Dict[str, Any]:
        """
        获取集群状态

        Returns:
            集群状态信息
        """
        if not self.state_manager:
            return {}

        state = await self.state_manager.get_state()

        return {
            "total_nodes": state.total_nodes,
            "online_nodes": state.online_nodes,
            "total_tasks": state.total_tasks,
            "running_tasks": state.running_tasks,
            "version": state.version,
            "updated_at": state.updated_at.isoformat(),
        }

    async def get_skill_status(self) -> Dict[str, Any]:
        """
        获取技能状态

        Returns:
            技能状态信息
        """
        if not self.skill_registry:
            return {}

        return await self.skill_registry.get_stats()

    async def get_scheduler_status(self) -> Dict[str, Any]:
        """
        获取调度器状态

        Returns:
            调度器状态信息
        """
        if not self.task_scheduler:
            return {}

        queue_stats = await self.task_scheduler.get_queue_stats()
        scheduler_stats = await self.task_scheduler.get_scheduler_stats()

        return {
            **queue_stats,
            **scheduler_stats,
        }


async def create_coordinator(config: Config) -> CoordinatorService:
    """
    创建协调器服务

    Args:
        config: 配置对象

    Returns:
        协调器服务实例
    """
    coordinator = CoordinatorService(config)
    await coordinator.start()
    return coordinator
