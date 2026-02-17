"""
OpenClaw 集群系统 - 数据库层

使用SQLite和aiosqlite实现异步数据库操作
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from common.logging import get_logger

logger = get_logger(__name__)


class Database:
    """
    异步SQLite数据库管理器

    提供数据库连接、初始化和基本CRUD操作
    """

    def __init__(self, db_path: str = "./data/cluster.db"):
        """
        初始化数据库管理器

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def connect(self) -> aiosqlite.Connection:
        """
        建立数据库连接

        Returns:
            数据库连接对象
        """
        if self._connection is None:
            async with self._lock:
                if self._connection is None:
                    self._connection = await aiosqlite.connect(self.db_path)
                    # 启用外键约束
                    await self._connection.execute("PRAGMA foreign_keys = ON")
                    # 设置WAL模式以提升并发性能
                    await self._connection.execute("PRAGMA journal_mode = WAL")
                    # 设置行级锁
                    await self._connection.execute("PRAGMA busy_timeout = 5000")
                    logger.info(f"数据库连接已建立: {self.db_path}")
        return self._connection

    async def close(self):
        """关闭数据库连接"""
        if self._connection:
            async with self._lock:
                if self._connection:
                    await self._connection.close()
                    self._connection = None
                    logger.info("数据库连接已关闭")

    async def initialize(self):
        """
        初始化数据库表结构

        创建所有必需的表和索引
        """
        conn = await self.connect()

        # 创建任务表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                task_type TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,

                required_skills TEXT NOT NULL,
                optional_skills TEXT,

                status TEXT NOT NULL,
                priority INTEGER NOT NULL,
                assigned_node TEXT,
                submitted_at TEXT,
                scheduled_at TEXT,
                started_at TEXT,
                completed_at TEXT,

                parameters TEXT,
                timeout INTEGER,
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,

                user_id TEXT,
                affinity_tags TEXT,

                result TEXT,
                error TEXT,

                metadata TEXT,

                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 创建节点表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
                node_id TEXT PRIMARY KEY,
                hostname TEXT NOT NULL,
                platform TEXT NOT NULL,
                arch TEXT NOT NULL,

                status TEXT NOT NULL,
                cpu_usage REAL DEFAULT 0.0,
                memory_usage REAL DEFAULT 0.0,
                disk_usage REAL DEFAULT 0.0,

                available_skills TEXT NOT NULL,
                max_concurrent_tasks INTEGER DEFAULT 5,
                running_tasks INTEGER DEFAULT 0,

                ip_address TEXT DEFAULT '',
                tailscale_ip TEXT DEFAULT '',
                port INTEGER DEFAULT 18789,

                total_tasks_processed INTEGER DEFAULT 0,
                successful_tasks INTEGER DEFAULT 0,
                failed_tasks INTEGER DEFAULT 0,
                average_execution_time REAL DEFAULT 0.0,

                registered_at TEXT,
                last_heartbeat TEXT,

                tags TEXT,

                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 创建索引 - 任务表
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_assigned_node ON tasks(assigned_node)"
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_type ON tasks(task_type)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_submitted_at ON tasks(submitted_at)"
        )

        # 创建索引 - 节点表
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_status ON nodes(status)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_nodes_last_heartbeat ON nodes(last_heartbeat)"
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_platform ON nodes(platform)")

        # 创建触发器 - 自动更新updated_at
        await conn.execute("""
            CREATE TRIGGER IF NOT EXISTS update_tasks_timestamp
            AFTER UPDATE ON tasks
            FOR EACH ROW
            BEGIN
                UPDATE tasks SET updated_at = CURRENT_TIMESTAMP WHERE task_id = OLD.task_id;
            END
        """)

        await conn.execute("""
            CREATE TRIGGER IF NOT EXISTS update_nodes_timestamp
            AFTER UPDATE ON nodes
            FOR EACH ROW
            BEGIN
                UPDATE nodes SET updated_at = CURRENT_TIMESTAMP WHERE node_id = OLD.node_id;
            END
        """)

        await conn.commit()
        logger.info("数据库表结构初始化完成")

    async def execute_transaction(self, operations: List[Dict[str, Any]]) -> bool:
        """
        执行事务操作

        Args:
            operations: 操作列表，每个操作包含sql和params

        Returns:
            是否成功
        """
        conn = await self.connect()
        try:
            async with self._lock:
                await conn.execute("BEGIN IMMEDIATE")
                try:
                    for op in operations:
                        await conn.execute(op["sql"], op.get("params", ()))
                    await conn.commit()
                    return True
                except Exception as e:
                    await conn.rollback()
                    logger.error(f"事务执行失败: {e}")
                    raise
        except Exception as e:
            logger.error(f"事务启动失败: {e}")
            raise

    async def backup(self, backup_path: str):
        """
        备份数据库

        Args:
            backup_path: 备份文件路径
        """
        conn = await self.connect()
        backup_file = Path(backup_path)
        backup_file.parent.mkdir(parents=True, exist_ok=True)

        # 使用SQLite的备份API
        async with aiosqlite.connect(backup_path) as backup_conn:
            await conn.backup(backup_conn)
            logger.info(f"数据库备份完成: {backup_path}")

    async def vacuum(self):
        """优化数据库"""
        conn = await self.connect()
        await conn.execute("VACUUM")
        await conn.commit()
        logger.info("数据库优化完成")

    async def get_stats(self) -> Dict[str, Any]:
        """
        获取数据库统计信息

        Returns:
            统计信息字典
        """
        conn = await self.connect()

        # 获取表大小
        async with conn.execute("SELECT COUNT(*) FROM tasks") as cursor:
            task_count = (await cursor.fetchone())[0]

        async with conn.execute("SELECT COUNT(*) FROM nodes") as cursor:
            node_count = (await cursor.fetchone())[0]

        # 获取数据库文件大小
        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0

        # 按状态统计任务
        async with conn.execute("""
            SELECT status, COUNT(*) as count
            FROM tasks
            GROUP BY status
        """) as cursor:
            task_stats = {row[0]: row[1] for row in await cursor.fetchall()}

        # 按状态统计节点
        async with conn.execute("""
            SELECT status, COUNT(*) as count
            FROM nodes
            GROUP BY status
        """) as cursor:
            node_stats = {row[0]: row[1] for row in await cursor.fetchall()}

        return {
            "db_size": db_size,
            "db_path": str(self.db_path),
            "task_count": task_count,
            "node_count": node_count,
            "task_stats": task_stats,
            "node_stats": node_stats,
        }


def _serialize_datetime(dt: Optional[datetime]) -> Optional[str]:
    """序列化datetime对象"""
    return dt.isoformat() if dt else None


def _deserialize_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """反序列化datetime对象"""
    return datetime.fromisoformat(dt_str) if dt_str else None


def _serialize_list(lst: Optional[List[str]]) -> Optional[str]:
    """序列化列表为JSON字符串"""
    return json.dumps(lst) if lst else None


def _deserialize_list(json_str: Optional[str]) -> List[str]:
    """反序列化JSON字符串为列表"""
    return json.loads(json_str) if json_str else []


def _serialize_dict(d: Optional[Dict[str, Any]]) -> Optional[str]:
    """序列化字典为JSON字符串"""
    return json.dumps(d) if d else None


def _deserialize_dict(json_str: Optional[str]) -> Dict[str, Any]:
    """反序列化JSON字符串为字典"""
    return json.loads(json_str) if json_str else {}
