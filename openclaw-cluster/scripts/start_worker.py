#!/usr/bin/env python3
"""
OpenClaw 集群系统 - 工作节点启动脚本

启动工作节点，连接到协调器并执行任务
"""
import asyncio
import sys
import os
import signal
import argparse
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from common.logging import get_logger
from common.config import Config, load_config
from worker.worker_service import WorkerService

logger = get_logger(__name__)


class WorkerRunner:
    """工作节点运行器"""

    def __init__(self, config_path: str = None, node_id: str = None):
        """
        初始化运行器

        Args:
            config_path: 配置文件路径
            node_id: 节点ID（可选）
        """
        self.config_path = config_path
        self.node_id = node_id
        self.worker: WorkerService = None
        self.shutdown_event = asyncio.Event()

    async def start(self):
        """启动工作节点"""
        # 加载配置
        if self.config_path and os.path.exists(self.config_path):
            logger.info(f"加载配置文件: {self.config_path}")
            config = load_config(self.config_path)
        else:
            logger.info("使用默认配置")
            config = self._create_default_config()

        # 创建工作节点
        self.worker = WorkerService(config, node_id=self.node_id)

        # 设置信号处理
        self._setup_signal_handlers()

        # 启动工作节点
        await self.worker.start()

        logger.info("=" * 60)
        logger.info("🚀 OpenClaw 工作节点已启动")
        logger.info("=" * 60)
        logger.info(f"   节点ID: {self.worker.node_id}")
        logger.info(f"   主机名: {self.worker.hostname}")
        logger.info(f"   平台: {self.worker.platform}")
        logger.info(f"   架构: {self.worker.arch}")
        logger.info("=" * 60)

        # 获取系统指标
        metrics = await self.worker.get_system_metrics()
        logger.info(f"   CPU: {metrics['cpu_usage']:.1f}%")
        logger.info(f"   内存: {metrics['memory_usage']:.1f}%")
        logger.info(f"   磁盘: {metrics['disk_usage']:.1f}%")
        logger.info("=" * 60)

        # 等待关闭信号
        await self.shutdown_event.wait()

        # 停止工作节点
        await self.worker.stop()

        logger.info("工作节点已关闭")

    def _create_default_config(self) -> Config:
        """创建默认配置"""
        import socket

        class Coordinator:
            host = "localhost"
            port = 8888

        class Worker:
            max_concurrent_tasks = 5
            heartbeat_interval = 5
            skills_dir = "./skills"
            port = 18789

        class Communication:
            nats_url = "nats://localhost:4222"

        class Log:
            level = "INFO"
            format = "json"

        config = Config()
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
    parser = argparse.ArgumentParser(description="OpenClaw 集群工作节点")
    parser.add_argument(
        "-c", "--config",
        type=str,
        default=None,
        help="配置文件路径",
    )
    parser.add_argument(
        "-n", "--node-id",
        type=str,
        default=None,
        help="节点ID（可选，自动生成）",
    )
    parser.add_argument(
        "--coordinator-host",
        type=str,
        default=None,
        help="协调器地址",
    )
    parser.add_argument(
        "--coordinator-port",
        type=int,
        default=None,
        help="协调器端口",
    )
    parser.add_argument(
        "--skills-dir",
        type=str,
        default=None,
        help="技能目录",
    )

    args = parser.parse_args()

    # 创建运行器
    runner = WorkerRunner(config_path=args.config, node_id=args.node_id)

    # 如果有命令行参数，覆盖配置
    if args.coordinator_host or args.coordinator_port or args.skills_dir:
        logger.info("使用命令行参数启动...")
        config = runner._create_default_config()
        if args.coordinator_host:
            config.coordinator.host = args.coordinator_host
        if args.coordinator_port:
            config.coordinator.port = args.coordinator_port
        if args.skills_dir:
            config.worker.skills_dir = args.skills_dir
        runner.worker = WorkerService(config, node_id=args.node_id)

    # 启动工作节点
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
