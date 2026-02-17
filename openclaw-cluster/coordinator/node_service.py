"""
OpenClaw 集群系统 - 节点注册服务

处理工作节点的注册、验证和管理
"""
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List
import socket

from common.models import NodeInfo, NodeStatus
from common.logging import get_logger
from storage.repositories import NodeRepository
from storage.database import Database

logger = get_logger(__name__)


class NodeRegistrationService:
    """
    节点注册服务

    负责处理节点的注册请求、验证节点信息、分配节点ID
    """

    def __init__(self, database: Database):
        """
        初始化节点注册服务

        Args:
            database: 数据库实例
        """
        self.db = database
        self.node_repo = NodeRepository(database)
        logger.info("节点注册服务初始化完成")

    async def register_node(
        self,
        hostname: str,
        platform: str,
        arch: str,
        available_skills: List[str],
        ip_address: str = "",
        tailscale_ip: str = "",
        port: int = 18789,
        max_concurrent_tasks: int = 5,
        tags: Optional[List[str]] = None,
        node_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        注册新节点

        Args:
            hostname: 主机名
            platform: 平台 (macos/windows/linux)
            arch: 架构 (x64/arm64)
            available_skills: 可用技能列表
            ip_address: IP地址
            tailscale_ip: Tailscale IP
            port: 服务端口
            max_concurrent_tasks: 最大并发任务数
            tags: 节点标签
            node_id: 指定的节点ID（可选）

        Returns:
            注册结果字典，包含 success, node_id, message 等字段

        Raises:
            ValueError: 参数验证失败
        """
        try:
            # 验证必需参数
            self._validate_node_info(
                hostname=hostname,
                platform=platform,
                arch=arch,
                available_skills=available_skills,
            )

            # 检查节点是否已注册（基于主机名）
            existing_node = await self._find_node_by_hostname(hostname)
            if existing_node:
                # 更新现有节点的信息
                logger.info(f"节点 {existing_node.node_id} 重新注册，更新信息")
                await self._update_existing_node(
                    existing_node,
                    available_skills,
                    ip_address,
                    tailscale_ip,
                    port,
                    max_concurrent_tasks,
                    tags,
                )
                return {
                    "success": True,
                    "node_id": existing_node.node_id,
                    "message": "节点重新注册成功",
                    "registered": False,  # 非新注册
                    "node_info": self._serialize_node(existing_node),
                }

            # 生成或使用指定的节点ID
            final_node_id = node_id or self._generate_node_id(hostname)

            # 创建节点信息对象
            node_info = NodeInfo(
                node_id=final_node_id,
                hostname=hostname,
                platform=platform,
                arch=arch,
                status=NodeStatus.ONLINE,
                available_skills=available_skills,
                max_concurrent_tasks=max_concurrent_tasks,
                ip_address=ip_address,
                tailscale_ip=tailscale_ip,
                port=port,
                registered_at=datetime.now(),
                last_heartbeat=datetime.now(),
                tags=tags or [],
            )

            # 保存到数据库
            success = await self.node_repo.create(node_info)

            if success:
                logger.info(
                    f"节点注册成功: {final_node_id} ({hostname}) "
                    f"技能: {', '.join(available_skills)}"
                )
                return {
                    "success": True,
                    "node_id": final_node_id,
                    "message": "节点注册成功",
                    "registered": True,
                    "node_info": self._serialize_node(node_info),
                }
            else:
                logger.error(f"节点注册失败: {final_node_id}")
                return {
                    "success": False,
                    "node_id": final_node_id,
                    "message": "数据库保存失败",
                    "registered": False,
                }

        except ValueError as e:
            logger.warning(f"节点注册参数验证失败: {e}")
            return {
                "success": False,
                "node_id": None,
                "message": f"参数验证失败: {str(e)}",
                "registered": False,
            }
        except Exception as e:
            logger.error(f"节点注册时发生错误: {e}", exc_info=True)
            return {
                "success": False,
                "node_id": None,
                "message": f"注册失败: {str(e)}",
                "registered": False,
            }

    async def unregister_node(self, node_id: str) -> bool:
        """
        注销节点（标记为离线）

        Args:
            node_id: 节点ID

        Returns:
            是否注销成功
        """
        try:
            success = await self.node_repo.update_status(node_id, NodeStatus.OFFLINE)
            if success:
                logger.info(f"节点 {node_id} 已注销")
            else:
                logger.warning(f"节点 {node_id} 注销失败")
            return success
        except Exception as e:
            logger.error(f"注销节点 {node_id} 时发生错误: {e}")
            return False

    async def get_node(self, node_id: str) -> Optional[NodeInfo]:
        """
        获取节点信息

        Args:
            node_id: 节点ID

        Returns:
            节点信息对象或None
        """
        return await self.node_repo.get(node_id)

    async def list_all_nodes(self) -> List[NodeInfo]:
        """
        获取所有节点

        Returns:
            节点列表
        """
        return await self.node_repo.get_all_nodes()

    async def list_online_nodes(self) -> List[NodeInfo]:
        """
        获取所有在线节点

        Returns:
            在线节点列表
        """
        return await self.node_repo.list_online_nodes()

    async def find_nodes_by_skill(self, skill: str) -> List[NodeInfo]:
        """
        查找具有特定技能的节点

        Args:
            skill: 技能名称

        Returns:
            节点列表
        """
        return await self.node_repo.find_by_skill(skill)

    def _validate_node_info(
        self,
        hostname: str,
        platform: str,
        arch: str,
        available_skills: List[str],
    ):
        """
        验证节点信息

        Args:
            hostname: 主机名
            platform: 平台
            arch: 架构
            available_skills: 可用技能列表

        Raises:
            ValueError: 参数验证失败
        """
        if not hostname or not hostname.strip():
            raise ValueError("主机名不能为空")

        if platform not in ["macos", "windows", "linux"]:
            raise ValueError(f"不支持的平台: {platform}")

        if arch not in ["x64", "arm64", "x86", "arm"]:
            raise ValueError(f"不支持的架构: {arch}")

        if not available_skills or not isinstance(available_skills, list):
            raise ValueError("可用技能列表不能为空")

        # 验证技能名称格式
        for skill in available_skills:
            if not isinstance(skill, str) or not skill.strip():
                raise ValueError("技能名称必须是非空字符串")

    def _generate_node_id(self, hostname: str) -> str:
        """
        生成节点ID

        Args:
            hostname: 主机名

        Returns:
            节点ID
        """
        # 使用主机名和UUID的组合生成唯一ID
        short_uuid = uuid.uuid4().hex[:8]
        hostname_part = hostname.split(".")[0][:16]  # 取主机名前16个字符
        return f"node_{hostname_part}_{short_uuid}"

    async def _find_node_by_hostname(self, hostname: str) -> Optional[NodeInfo]:
        """
        根据主机名查找节点

        Args:
            hostname: 主机名

        Returns:
            节点信息对象或None
        """
        all_nodes = await self.node_repo.get_all_nodes()
        for node in all_nodes:
            if node.hostname == hostname:
                return node
        return None

    async def _update_existing_node(
        self,
        node: NodeInfo,
        available_skills: List[str],
        ip_address: str,
        tailscale_ip: str,
        port: int,
        max_concurrent_tasks: int,
        tags: Optional[List[str]],
    ):
        """
        更新现有节点的信息

        Args:
            node: 现有节点对象
            available_skills: 可用技能列表
            ip_address: IP地址
            tailscale_ip: Tailscale IP
            port: 服务端口
            max_concurrent_tasks: 最大并发任务数
            tags: 节点标签
        """
        # 更新节点信息
        node.available_skills = available_skills
        node.ip_address = ip_address
        node.tailscale_ip = tailscale_ip
        node.port = port
        node.max_concurrent_tasks = max_concurrent_tasks
        if tags is not None:
            node.tags = tags
        node.status = NodeStatus.ONLINE
        node.last_heartbeat = datetime.now()

        # 保存到数据库
        await self.node_repo.update(node)

    def _serialize_node(self, node: NodeInfo) -> Dict[str, Any]:
        """
        序列化节点信息为字典

        Args:
            node: 节点信息对象

        Returns:
            节点信息字典
        """
        return {
            "node_id": node.node_id,
            "hostname": node.hostname,
            "platform": node.platform,
            "arch": node.arch,
            "status": node.status.value,
            "available_skills": node.available_skills,
            "max_concurrent_tasks": node.max_concurrent_tasks,
            "running_tasks": node.running_tasks,
            "ip_address": node.ip_address,
            "tailscale_ip": node.tailscale_ip,
            "port": node.port,
            "cpu_usage": node.cpu_usage,
            "memory_usage": node.memory_usage,
            "disk_usage": node.disk_usage,
            "total_tasks_processed": node.total_tasks_processed,
            "successful_tasks": node.successful_tasks,
            "failed_tasks": node.failed_tasks,
            "average_execution_time": node.average_execution_time,
            "registered_at": node.registered_at.isoformat() if node.registered_at else None,
            "last_heartbeat": node.last_heartbeat.isoformat() if node.last_heartbeat else None,
            "tags": node.tags,
        }
