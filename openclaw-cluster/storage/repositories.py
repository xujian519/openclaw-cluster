"""
OpenClaw 集群系统 - 数据仓库层

实现Repository模式，提供类型化的数据访问接口
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import json

from common.models import (
    Task,
    TaskStatus,
    TaskType,
    TaskPriority,
    NodeInfo,
    NodeStatus,
)
from common.logging import get_logger
from .database import (
    Database,
    _serialize_datetime,
    _deserialize_datetime,
    _serialize_list,
    _deserialize_list,
    _serialize_dict,
    _deserialize_dict,
)

logger = get_logger(__name__)


class TaskRepository:
    """
    任务数据仓库

    提供任务的CRUD操作和查询功能
    """

    def __init__(self, database: Database):
        """
        初始化任务仓库

        Args:
            database: 数据库实例
        """
        self.db = database

    async def create(self, task: Task) -> bool:
        """
        创建新任务

        Args:
            task: 任务对象

        Returns:
            是否创建成功
        """
        conn = await self.db.connect()
        try:
            await conn.execute(
                """
                INSERT INTO tasks (
                    task_id, task_type, name, description,
                    required_skills, optional_skills,
                    status, priority, assigned_node,
                    submitted_at, scheduled_at, started_at, completed_at,
                    parameters, timeout, retry_count, max_retries,
                    user_id, affinity_tags, result, error, metadata,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    task.task_type.value,
                    task.name,
                    task.description,
                    _serialize_list(task.required_skills),
                    _serialize_list(task.optional_skills),
                    task.status.value,
                    task.priority.value,
                    task.assigned_node,
                    _serialize_datetime(task.submitted_at),
                    _serialize_datetime(task.scheduled_at),
                    _serialize_datetime(task.started_at),
                    _serialize_datetime(task.completed_at),
                    _serialize_dict(task.parameters),
                    task.timeout,
                    task.retry_count,
                    task.max_retries,
                    task.user_id,
                    _serialize_list(task.affinity_tags),
                    _serialize_dict(task.result) if task.result else None,
                    task.error,
                    _serialize_dict(task.metadata),
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                ),
            )
            await conn.commit()
            logger.info(f"任务创建成功: {task.task_id}")
            return True
        except Exception as e:
            logger.error(f"任务创建失败 {task.task_id}: {e}")
            return False

    async def get(self, task_id: str) -> Optional[Task]:
        """
        获取任务

        Args:
            task_id: 任务ID

        Returns:
            任务对象或None
        """
        conn = await self.db.connect()
        async with conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_task(row)
        return None

    async def update(self, task: Task) -> bool:
        """
        更新任务

        Args:
            task: 任务对象

        Returns:
            是否更新成功
        """
        conn = await self.db.connect()
        try:
            await conn.execute(
                """
                UPDATE tasks SET
                    task_type = ?, name = ?, description = ?,
                    required_skills = ?, optional_skills = ?,
                    status = ?, priority = ?, assigned_node = ?,
                    submitted_at = ?, scheduled_at = ?, started_at = ?, completed_at = ?,
                    parameters = ?, timeout = ?, retry_count = ?, max_retries = ?,
                    user_id = ?, affinity_tags = ?, result = ?, error = ?, metadata = ?
                WHERE task_id = ?
                """,
                (
                    task.task_type.value,
                    task.name,
                    task.description,
                    _serialize_list(task.required_skills),
                    _serialize_list(task.optional_skills),
                    task.status.value,
                    task.priority.value,
                    task.assigned_node,
                    _serialize_datetime(task.submitted_at),
                    _serialize_datetime(task.scheduled_at),
                    _serialize_datetime(task.started_at),
                    _serialize_datetime(task.completed_at),
                    _serialize_dict(task.parameters),
                    task.timeout,
                    task.retry_count,
                    task.max_retries,
                    task.user_id,
                    _serialize_list(task.affinity_tags),
                    _serialize_dict(task.result) if task.result else None,
                    task.error,
                    _serialize_dict(task.metadata),
                    task.task_id,
                ),
            )
            await conn.commit()
            logger.debug(f"任务更新成功: {task.task_id}")
            return True
        except Exception as e:
            logger.error(f"任务更新失败 {task.task_id}: {e}")
            return False

    async def delete(self, task_id: str) -> bool:
        """
        删除任务

        Args:
            task_id: 任务ID

        Returns:
            是否删除成功
        """
        conn = await self.db.connect()
        try:
            await conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            await conn.commit()
            logger.info(f"任务删除成功: {task_id}")
            return True
        except Exception as e:
            logger.error(f"任务删除失败 {task_id}: {e}")
            return False

    async def list_by_status(
        self, status: TaskStatus, limit: Optional[int] = None
    ) -> List[Task]:
        """
        按状态查询任务

        Args:
            status: 任务状态
            limit: 限制数量

        Returns:
            任务列表
        """
        conn = await self.db.connect()
        if limit:
            async with conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY submitted_at DESC LIMIT ?",
                (status.value, limit),
            ) as cursor:
                rows = await cursor.fetchall()
        else:
            async with conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY submitted_at DESC",
                (status.value,),
            ) as cursor:
                rows = await cursor.fetchall()

        return [self._row_to_task(row) for row in rows]

    async def list_by_node(self, node_id: str) -> List[Task]:
        """
        查询节点的所有任务

        Args:
            node_id: 节点ID

        Returns:
            任务列表
        """
        conn = await self.db.connect()
        async with conn.execute(
            "SELECT * FROM tasks WHERE assigned_node = ? ORDER BY submitted_at DESC",
            (node_id,),
        ) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_task(row) for row in rows]

    async def list_by_user(self, user_id: str, limit: int = 100) -> List[Task]:
        """
        查询用户的任务

        Args:
            user_id: 用户ID
            limit: 限制数量

        Returns:
            任务列表
        """
        conn = await self.db.connect()
        async with conn.execute(
            "SELECT * FROM tasks WHERE user_id = ? ORDER BY submitted_at DESC LIMIT ?",
            (user_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_task(row) for row in rows]

    async def list_pending_tasks(self, limit: int = 50) -> List[Task]:
        """
        获取待处理任务（按优先级排序）

        Args:
            limit: 限制数量

        Returns:
            任务列表
        """
        conn = await self.db.connect()
        async with conn.execute(
            """
            SELECT * FROM tasks
            WHERE status IN (?, ?)
            ORDER BY priority ASC, submitted_at ASC
            LIMIT ?
            """,
            (TaskStatus.PENDING.value, TaskStatus.SCHEDULED.value, limit),
        ) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_task(row) for row in rows]

    async def count_by_status(self, status: Optional[TaskStatus] = None) -> int:
        """
        统计任务数量

        Args:
            status: 任务状态，None表示统计所有

        Returns:
            任务数量
        """
        conn = await self.db.connect()
        if status:
            async with conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status = ?", (status.value,)
            ) as cursor:
                result = await cursor.fetchone()
                return result[0] if result else 0
        else:
            async with conn.execute("SELECT COUNT(*) FROM tasks") as cursor:
                result = await cursor.fetchone()
                return result[0] if result else 0

    async def cleanup_old_tasks(
        self, days: int = 30, keep_status: List[TaskStatus] = None
    ) -> int:
        """
        清理旧任务

        Args:
            days: 保留天数
            keep_status: 要保留的任务状态列表

        Returns:
            清理的任务数量
        """
        if keep_status is None:
            keep_status = [TaskStatus.RUNNING, TaskStatus.PENDING, TaskStatus.SCHEDULED]

        conn = await self.db.connect()
        cutoff_date = datetime.now() - timedelta(days=days)

        # 构建要排除的状态列表
        exclude_statuses = [s.value for s in keep_status]

        cursor = await conn.execute(
            """
            DELETE FROM tasks
            WHERE completed_at < ?
            AND status NOT IN ({})
            """.format(
                ",".join(["?"] * len(exclude_statuses))
            ),
            [cutoff_date.isoformat()] + exclude_statuses,
        )

        deleted_count = cursor.rowcount
        await conn.commit()
        logger.info(f"清理了 {deleted_count} 个旧任务")
        return deleted_count

    def _row_to_task(self, row: tuple) -> Task:
        """将数据库行转换为Task对象"""
        return Task(
            task_id=row[0],
            task_type=TaskType(row[1]),
            name=row[2],
            description=row[3],
            required_skills=_deserialize_list(row[4]),
            optional_skills=_deserialize_list(row[5]),
            status=TaskStatus(row[6]),
            priority=TaskPriority(row[7]),
            assigned_node=row[8],
            submitted_at=_deserialize_datetime(row[9]),
            scheduled_at=_deserialize_datetime(row[10]),
            started_at=_deserialize_datetime(row[11]),
            completed_at=_deserialize_datetime(row[12]),
            parameters=_deserialize_dict(row[13]),
            timeout=row[14],
            retry_count=row[15],
            max_retries=row[16],
            user_id=row[17],
            affinity_tags=_deserialize_list(row[18]),
            result=_deserialize_dict(row[19]),
            error=row[20],
            metadata=_deserialize_dict(row[21]),
        )


class NodeRepository:
    """
    节点数据仓库

    提供节点的CRUD操作和查询功能
    """

    def __init__(self, database: Database):
        """
        初始化节点仓库

        Args:
            database: 数据库实例
        """
        self.db = database

    async def create(self, node: NodeInfo) -> bool:
        """
        创建新节点

        Args:
            node: 节点对象

        Returns:
            是否创建成功
        """
        conn = await self.db.connect()
        try:
            await conn.execute(
                """
                INSERT INTO nodes (
                    node_id, hostname, platform, arch,
                    status, cpu_usage, memory_usage, disk_usage,
                    available_skills, max_concurrent_tasks, running_tasks,
                    ip_address, tailscale_ip, port,
                    total_tasks_processed, successful_tasks, failed_tasks, average_execution_time,
                    registered_at, last_heartbeat, tags,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node.node_id,
                    node.hostname,
                    node.platform,
                    node.arch,
                    node.status.value,
                    node.cpu_usage,
                    node.memory_usage,
                    node.disk_usage,
                    _serialize_list(node.available_skills),
                    node.max_concurrent_tasks,
                    node.running_tasks,
                    node.ip_address,
                    node.tailscale_ip,
                    node.port,
                    node.total_tasks_processed,
                    node.successful_tasks,
                    node.failed_tasks,
                    node.average_execution_time,
                    _serialize_datetime(node.registered_at),
                    _serialize_datetime(node.last_heartbeat),
                    _serialize_list(node.tags),
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                ),
            )
            await conn.commit()
            logger.info(f"节点创建成功: {node.node_id}")
            return True
        except Exception as e:
            logger.error(f"节点创建失败 {node.node_id}: {e}")
            return False

    async def get(self, node_id: str) -> Optional[NodeInfo]:
        """
        获取节点

        Args:
            node_id: 节点ID

        Returns:
            节点对象或None
        """
        conn = await self.db.connect()
        async with conn.execute(
            "SELECT * FROM nodes WHERE node_id = ?", (node_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_node(row)
        return None

    async def update(self, node: NodeInfo) -> bool:
        """
        更新节点

        Args:
            node: 节点对象

        Returns:
            是否更新成功
        """
        conn = await self.db.connect()
        try:
            await conn.execute(
                """
                UPDATE nodes SET
                    hostname = ?, platform = ?, arch = ?,
                    status = ?, cpu_usage = ?, memory_usage = ?, disk_usage = ?,
                    available_skills = ?, max_concurrent_tasks = ?, running_tasks = ?,
                    ip_address = ?, tailscale_ip = ?, port = ?,
                    total_tasks_processed = ?, successful_tasks = ?, failed_tasks = ?, average_execution_time = ?,
                    registered_at = ?, last_heartbeat = ?, tags = ?
                WHERE node_id = ?
                """,
                (
                    node.hostname,
                    node.platform,
                    node.arch,
                    node.status.value,
                    node.cpu_usage,
                    node.memory_usage,
                    node.disk_usage,
                    _serialize_list(node.available_skills),
                    node.max_concurrent_tasks,
                    node.running_tasks,
                    node.ip_address,
                    node.tailscale_ip,
                    node.port,
                    node.total_tasks_processed,
                    node.successful_tasks,
                    node.failed_tasks,
                    node.average_execution_time,
                    _serialize_datetime(node.registered_at),
                    _serialize_datetime(node.last_heartbeat),
                    _serialize_list(node.tags),
                    node.node_id,
                ),
            )
            await conn.commit()
            logger.debug(f"节点更新成功: {node.node_id}")
            return True
        except Exception as e:
            logger.error(f"节点更新失败 {node.node_id}: {e}")
            return False

    async def delete(self, node_id: str) -> bool:
        """
        删除节点

        Args:
            node_id: 节点ID

        Returns:
            是否删除成功
        """
        conn = await self.db.connect()
        try:
            await conn.execute("DELETE FROM nodes WHERE node_id = ?", (node_id,))
            await conn.commit()
            logger.info(f"节点删除成功: {node_id}")
            return True
        except Exception as e:
            logger.error(f"节点删除失败 {node_id}: {e}")
            return False

    async def list_by_status(self, status: NodeStatus) -> List[NodeInfo]:
        """
        按状态查询节点

        Args:
            status: 节点状态

        Returns:
            节点列表
        """
        conn = await self.db.connect()
        async with conn.execute(
            "SELECT * FROM nodes WHERE status = ?", (status.value,)
        ) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_node(row) for row in rows]

    async def list_online_nodes(self) -> List[NodeInfo]:
        """
        获取所有在线节点

        Returns:
            在线节点列表
        """
        return await self.list_by_status(NodeStatus.ONLINE)

    async def get_all_nodes(self) -> List[NodeInfo]:
        """
        获取所有节点

        Returns:
            节点列表
        """
        conn = await self.db.connect()
        async with conn.execute("SELECT * FROM nodes ORDER BY registered_at DESC") as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_node(row) for row in rows]

    async def update_heartbeat(self, node_id: str) -> bool:
        """
        更新节点心跳时间

        Args:
            node_id: 节点ID

        Returns:
            是否更新成功
        """
        conn = await self.db.connect()
        try:
            await conn.execute(
                "UPDATE nodes SET last_heartbeat = ? WHERE node_id = ?",
                (datetime.now().isoformat(), node_id),
            )
            await conn.commit()
            return True
        except Exception as e:
            logger.error(f"更新心跳失败 {node_id}: {e}")
            return False

    async def update_status(self, node_id: str, status: NodeStatus) -> bool:
        """
        更新节点状态

        Args:
            node_id: 节点ID
            status: 新状态

        Returns:
            是否更新成功
        """
        conn = await self.db.connect()
        try:
            await conn.execute(
                "UPDATE nodes SET status = ?, last_heartbeat = ? WHERE node_id = ?",
                (status.value, datetime.now().isoformat(), node_id),
            )
            await conn.commit()
            logger.debug(f"节点状态更新: {node_id} -> {status.value}")
            return True
        except Exception as e:
            logger.error(f"更新状态失败 {node_id}: {e}")
            return False

    async def find_stale_nodes(self, timeout_seconds: int = 120) -> List[NodeInfo]:
        """
        查找失联节点（超时未发送心跳）

        Args:
            timeout_seconds: 超时秒数

        Returns:
            失联节点列表
        """
        conn = await self.db.connect()
        cutoff_time = datetime.now() - timedelta(seconds=timeout_seconds)

        async with conn.execute(
            """
            SELECT * FROM nodes
            WHERE last_heartbeat < ?
            AND status IN (?, ?)
            """,
            (cutoff_time.isoformat(), NodeStatus.ONLINE.value, NodeStatus.BUSY.value),
        ) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_node(row) for row in rows]

    async def find_by_skill(self, skill: str) -> List[NodeInfo]:
        """
        查找具有特定技能的节点

        Args:
            skill: 技能名称

        Returns:
            节点列表
        """
        conn = await self.db.connect()
        async with conn.execute(
            """
            SELECT * FROM nodes
            WHERE status = ?
            AND available_skills LIKE ?
            """,
            (NodeStatus.ONLINE.value, f"%{skill}%"),
        ) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_node(row) for row in rows]

    async def get_available_nodes(self) -> List[NodeInfo]:
        """
        获取可用节点（在线且未满载）

        Returns:
            可用节点列表
        """
        conn = await self.db.connect()
        async with conn.execute(
            """
            SELECT * FROM nodes
            WHERE status = ?
            AND running_tasks < max_concurrent_tasks
            ORDER BY running_tasks ASC
            """,
            (NodeStatus.ONLINE.value,),
        ) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_node(row) for row in rows]

    def _row_to_node(self, row: tuple) -> NodeInfo:
        """将数据库行转换为NodeInfo对象"""
        return NodeInfo(
            node_id=row[0],
            hostname=row[1],
            platform=row[2],
            arch=row[3],
            status=NodeStatus(row[4]),
            cpu_usage=row[5],
            memory_usage=row[6],
            disk_usage=row[7],
            available_skills=_deserialize_list(row[8]),
            max_concurrent_tasks=row[9],
            running_tasks=row[10],
            ip_address=row[11],
            tailscale_ip=row[12],
            port=row[13],
            total_tasks_processed=row[14],
            successful_tasks=row[15],
            failed_tasks=row[16],
            average_execution_time=row[17],
            registered_at=_deserialize_datetime(row[18]),
            last_heartbeat=_deserialize_datetime(row[19]),
            tags=_deserialize_list(row[20]),
        )
