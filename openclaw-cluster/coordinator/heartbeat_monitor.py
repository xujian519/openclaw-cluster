"""
OpenClaw 集群系统 - 心跳监控服务

监控工作节点的心跳，检测超时节点并触发告警
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from common.logging import get_logger
from common.models import NodeInfo, NodeStatus
from storage.database import Database
from storage.repositories import NodeRepository

logger = get_logger(__name__)


class HeartbeatMonitor:
    """
    心跳监控服务

    定期检查节点心跳，标记超时节点为离线状态
    """

    def __init__(
        self,
        database: Database,
        heartbeat_timeout: int = 90,
        check_interval: int = 30,
    ):
        """
        初始化心跳监控服务

        Args:
            database: 数据库实例
            heartbeat_timeout: 心跳超时时间（秒），默认90秒
            check_interval: 检查间隔（秒），默认30秒
        """
        self.db = database
        self.node_repo = NodeRepository(database)
        self.heartbeat_timeout = heartbeat_timeout
        self.check_interval = check_interval
        self.running = False
        self.monitor_task: Optional[asyncio.Task] = None

        # 告警回调函数列表
        self.alert_callbacks: List[Callable[[NodeInfo], None]] = []

        logger.info(
            f"心跳监控服务初始化完成 - 超时: {heartbeat_timeout}s, 检查间隔: {check_interval}s"
        )

    async def start(self):
        """启动心跳监控"""
        if self.running:
            logger.warning("心跳监控已经在运行")
            return

        self.running = True
        self.monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("心跳监控服务已启动")

    async def stop(self):
        """停止心跳监控"""
        if not self.running:
            return

        self.running = False

        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass

        logger.info("心跳监控服务已停止")

    async def check_heartbeat(self) -> Dict[str, Any]:
        """
        执行一次心跳检查

        Returns:
            检查结果字典，包含超时节点数量、告警节点列表等
        """
        try:
            # 查找所有超时节点
            stale_nodes = await self.node_repo.find_stale_nodes(self.heartbeat_timeout)

            if not stale_nodes:
                return {
                    "checked_at": datetime.now().isoformat(),
                    "timeout_nodes_count": 0,
                    "timeout_nodes": [],
                    "all_nodes_healthy": True,
                }

            # 标记超时节点为离线
            timeout_nodes = []
            for node in stale_nodes:
                # 只标记在线或忙碌的节点
                if node.status in [NodeStatus.ONLINE, NodeStatus.BUSY]:
                    await self._mark_node_offline(node)
                    timeout_nodes.append(
                        {
                            "node_id": node.node_id,
                            "hostname": node.hostname,
                            "last_heartbeat": (
                                node.last_heartbeat.isoformat() if node.last_heartbeat else None
                            ),
                            "timeout_seconds": (
                                (datetime.now() - node.last_heartbeat).total_seconds()
                                if node.last_heartbeat
                                else None
                            ),
                        }
                    )

            return {
                "checked_at": datetime.now().isoformat(),
                "timeout_nodes_count": len(timeout_nodes),
                "timeout_nodes": timeout_nodes,
                "all_nodes_healthy": len(timeout_nodes) == 0,
            }

        except Exception as e:
            logger.error(f"心跳检查时发生错误: {e}", exc_info=True)
            return {
                "checked_at": datetime.now().isoformat(),
                "error": str(e),
                "timeout_nodes_count": 0,
                "timeout_nodes": [],
            }

    async def update_node_heartbeat(
        self,
        node_id: str,
        cpu_usage: float = 0.0,
        memory_usage: float = 0.0,
        disk_usage: float = 0.0,
        running_tasks: int = 0,
    ) -> bool:
        """
        更新节点心跳信息

        Args:
            node_id: 节点ID
            cpu_usage: CPU使用率
            memory_usage: 内存使用率
            disk_usage: 磁盘使用率
            running_tasks: 当前运行任务数

        Returns:
            是否更新成功
        """
        try:
            # 获取节点信息
            node = await self.node_repo.get(node_id)
            if not node:
                logger.warning(f"收到未知节点的心跳: {node_id}")
                return False

            # 更新心跳时间和状态
            node.last_heartbeat = datetime.now()
            node.cpu_usage = cpu_usage
            node.memory_usage = memory_usage
            node.disk_usage = disk_usage
            node.running_tasks = running_tasks

            # 如果节点之前是离线状态，现在标记为在线
            if node.status == NodeStatus.OFFLINE:
                node.status = NodeStatus.ONLINE
                logger.info(f"节点 {node_id} 恢复在线")

            # 保存到数据库
            success = await self.node_repo.update(node)
            if success:
                logger.debug(f"更新节点心跳: {node_id}")

            return success

        except Exception as e:
            logger.error(f"更新节点心跳时发生错误 {node_id}: {e}")
            return False

    async def get_node_health_status(self, node_id: str) -> Dict[str, Any]:
        """
        获取节点健康状态

        Args:
            node_id: 节点ID

        Returns:
            健康状态字典
        """
        try:
            node = await self.node_repo.get(node_id)
            if not node:
                return {
                    "node_id": node_id,
                    "healthy": False,
                    "status": "not_found",
                    "message": "节点不存在",
                }

            # 计算心跳超时
            if node.last_heartbeat:
                time_since_heartbeat = datetime.now() - node.last_heartbeat
                is_timeout = time_since_heartbeat > timedelta(seconds=self.heartbeat_timeout)
            else:
                time_since_heartbeat = None
                is_timeout = True

            return {
                "node_id": node_id,
                "hostname": node.hostname,
                "healthy": node.status == NodeStatus.ONLINE and not is_timeout,
                "status": node.status.value,
                "last_heartbeat": node.last_heartbeat.isoformat() if node.last_heartbeat else None,
                "time_since_heartbeat": (
                    time_since_heartbeat.total_seconds() if time_since_heartbeat else None
                ),
                "is_timeout": is_timeout,
                "cpu_usage": node.cpu_usage,
                "memory_usage": node.memory_usage,
                "disk_usage": node.disk_usage,
                "running_tasks": node.running_tasks,
                "max_concurrent_tasks": node.max_concurrent_tasks,
                "available_capacity": node.max_concurrent_tasks - node.running_tasks,
            }

        except Exception as e:
            logger.error(f"获取节点健康状态时发生错误 {node_id}: {e}")
            return {
                "node_id": node_id,
                "healthy": False,
                "status": "error",
                "message": str(e),
            }

    async def get_cluster_health_summary(self) -> Dict[str, Any]:
        """
        获取集群健康状态摘要

        Returns:
            集群健康状态字典
        """
        try:
            all_nodes = await self.node_repo.get_all_nodes()

            # 统计各状态节点数量
            status_count = {status.value: 0 for status in NodeStatus}
            for node in all_nodes:
                status_count[node.status.value] += 1

            # 检查超时节点
            stale_nodes = await self.node_repo.find_stale_nodes(self.heartbeat_timeout)

            # 计算总容量
            total_capacity = sum(node.max_concurrent_tasks for node in all_nodes)
            used_capacity = sum(node.running_tasks for node in all_nodes)
            available_capacity = total_capacity - used_capacity

            return {
                "checked_at": datetime.now().isoformat(),
                "total_nodes": len(all_nodes),
                "nodes_by_status": status_count,
                "online_nodes": status_count.get("online", 0),
                "offline_nodes": status_count.get("offline", 0),
                "busy_nodes": status_count.get("busy", 0),
                "timeout_nodes_count": len(stale_nodes),
                "total_capacity": total_capacity,
                "used_capacity": used_capacity,
                "available_capacity": available_capacity,
                "capacity_utilization": (
                    (used_capacity / total_capacity * 100) if total_capacity > 0 else 0
                ),
            }

        except Exception as e:
            logger.error(f"获取集群健康状态时发生错误: {e}", exc_info=True)
            return {
                "checked_at": datetime.now().isoformat(),
                "error": str(e),
            }

    def add_alert_callback(self, callback: Callable[[NodeInfo], None]):
        """
        添加告警回调函数

        Args:
            callback: 回调函数，接收超时节点作为参数
        """
        self.alert_callbacks.append(callback)
        logger.info(f"已添加告警回调函数，当前总数: {len(self.alert_callbacks)}")

    def remove_alert_callback(self, callback: Callable[[NodeInfo], None]):
        """
        移除告警回调函数

        Args:
            callback: 要移除的回调函数
        """
        if callback in self.alert_callbacks:
            self.alert_callbacks.remove(callback)
            logger.info(f"已移除告警回调函数，当前总数: {len(self.alert_callbacks)}")

    async def _monitor_loop(self):
        """监控循环"""
        logger.info("心跳监控循环已启动")

        while self.running:
            try:
                # 执行心跳检查
                result = await self.check_heartbeat()

                # 如果有超时节点，记录日志
                if result.get("timeout_nodes_count", 0) > 0:
                    logger.warning(f"检测到 {result['timeout_nodes_count']} 个超时节点")
                    for node_info in result.get("timeout_nodes", []):
                        logger.warning(
                            f"  - {node_info['node_id']} ({node_info['hostname']}) "
                            f"超时 {node_info['timeout_seconds']:.1f} 秒"
                        )

                # 等待下一次检查
                await asyncio.sleep(self.check_interval)

            except asyncio.CancelledError:
                logger.info("心跳监控循环被取消")
                break
            except Exception as e:
                logger.error(f"心跳监控循环发生错误: {e}", exc_info=True)
                # 发生错误后等待一段时间再继续
                await asyncio.sleep(self.check_interval)

    async def _mark_node_offline(self, node: NodeInfo):
        """
        标记节点为离线状态

        Args:
            node: 节点信息对象
        """
        try:
            # 更新节点状态
            await self.node_repo.update_status(node.node_id, NodeStatus.OFFLINE)

            logger.warning(f"节点 {node.node_id} ({node.hostname}) 心跳超时，已标记为离线")

            # 触发告警回调
            for callback in self.alert_callbacks:
                try:
                    callback(node)
                except Exception as e:
                    logger.error(f"告警回调函数执行失败: {e}")

        except Exception as e:
            logger.error(f"标记节点离线时发生错误 {node.node_id}: {e}")


# 默认的告警回调函数示例
async def default_alert_callback(node: NodeInfo):
    """
    默认告警回调函数

    Args:
        node: 超时的节点信息
    """
    logger.warning(
        f"🚨 节点告警: {node.node_id} ({node.hostname}) 心跳超时，"
        f"最后心跳时间: {node.last_heartbeat}"
    )
