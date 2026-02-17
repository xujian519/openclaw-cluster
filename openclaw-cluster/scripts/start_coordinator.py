#!/usr/bin/env python3
"""
OpenClaw 集群系统 - 协调器启动脚本

启动协调器服务，管理整个集群
"""

import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from common.config import Config, load_config
from common.logging import get_logger
from coordinator.coordinator_service import CoordinatorService

logger = get_logger(__name__)


class CoordinatorRunner:
    """协调器运行器"""

    def __init__(self, config_path: str = None):
        """
        初始化运行器

        Args:
            config_path: 配置文件路径
        """
        self.config_path = config_path
        self.coordinator: CoordinatorService = None
        self.shutdown_event = asyncio.Event()

    async def start(self):
        """启动协调器"""
        # 加载配置
        if self.config_path and os.path.exists(self.config_path):
            logger.info(f"加载配置文件: {self.config_path}")
            config = load_config(self.config_path)
        else:
            logger.info("使用默认配置")
            config = self._create_default_config()

        # 创建协调器
        self.coordinator = CoordinatorService(config)

        # 设置信号处理
        self._setup_signal_handlers()

        # 启动协调器
        await self.coordinator.start()

        logger.info("=" * 60)
        logger.info("🚀 OpenClaw 协调器服务已启动")
        logger.info("=" * 60)
        logger.info(f"   API 地址: http://{config.coordinator.host}:{config.coordinator.port}")
        logger.info("=" * 60)

        # 等待关闭信号
        await self.shutdown_event.wait()

        # 停止协调器
        await self.coordinator.stop()

        logger.info("协调器服务已关闭")

    def _create_default_config(self) -> Config:
        """创建默认配置"""

        class Storage:
            type = "sqlite"
            path = "./data/cluster.db"

        class Coordinator:
            host = "0.0.0.0"
            port = 8888
            heartbeat_timeout = 90
            heartbeat_check_interval = 30

        class Worker:
            max_concurrent_tasks = 5
            heartbeat_interval = 5
            skills_dir = "./skills"

        class Communication:
            nats_url = "nats://localhost:4222"

        class Log:
            level = "INFO"
            format = "json"

        config = Config()
        config.storage = Storage()
        config.coordinator = Coordinator()
        config.worker = Worker()
        config.communication = Communication()
        config.log = Log()

        return config

    def _setup_signal_handlers(self):
        """设置信号处理器"""

        def signal_handler(sig, frame):
            logger.info(f"收到信号: {sig}, 正在关闭...")
            self.shutdown_event.set()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="OpenClaw 集群协调器")
    parser.add_argument(
        "-c",
        "--config",
        type=str,
        default=None,
        help="配置文件路径",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="监听地址",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="监听端口",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="数据库路径",
    )

    args = parser.parse_args()

    # 创建运行器
    runner = CoordinatorRunner(config_path=args.config)

    # 如果有命令行参数，覆盖配置
    if args.host or args.port or args.db_path:
        logger.info("使用命令行参数启动...")
        config = runner._create_default_config()
        if args.host:
            config.coordinator.host = args.host
        if args.port:
            config.coordinator.port = args.port
        if args.db_path:
            config.storage.path = args.db_path
        runner.coordinator = CoordinatorService(config)

    # 启动协调器
    try:
        await runner.start()
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭...")
    except Exception as e:
        logger.error(f"启动失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
