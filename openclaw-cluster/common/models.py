"""
OpenClaw 集群系统 - 数据模型

定义系统中使用的所有数据结构
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class TaskStatus(Enum):
    """任务状态"""

    PENDING = "pending"  # 等待调度
    SCHEDULED = "scheduled"  # 已调度
    RUNNING = "running"  # 执行中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败
    CANCELLED = "cancelled"  # 已取消
    TIMEOUT = "timeout"  # 超时


class TaskType(Enum):
    """任务类型"""

    INTERACTIVE = "interactive"  # 交互式任务
    BATCH = "batch"  # 批处理任务
    COMPUTE_INTENSIVE = "compute_intensive"  # 计算密集型
    IO_INTENSIVE = "io_intensive"  # IO密集型
    DAEMON = "daemon"  # 守护进程


class TaskPriority(Enum):
    """任务优先级"""

    CRITICAL = 0  # 关键任务
    HIGH = 1  # 高优先级
    NORMAL = 2  # 普通优先级
    LOW = 3  # 低优先级


class NodeStatus(Enum):
    """节点状态"""

    ONLINE = "online"  # 在线
    OFFLINE = "offline"  # 离线
    BUSY = "busy"  # 忙碌
    MAINTENANCE = "maintenance"  # 维护中
    ERROR = "error"  # 错误


@dataclass
class Task:
    """任务模型"""

    # 基本信息
    task_id: str  # 任务ID
    task_type: TaskType  # 任务类型
    name: str  # 任务名称
    description: str  # 任务描述

    # 技能需求
    required_skills: List[str]  # 必需技能
    optional_skills: Optional[List[str]] = None  # 可选技能

    # 调度信息
    status: TaskStatus = TaskStatus.PENDING  # 任务状态
    priority: TaskPriority = TaskPriority.NORMAL  # 任务优先级
    assigned_node: Optional[str] = None  # 分配的节点ID
    submitted_at: Optional[datetime] = None  # 提交时间
    scheduled_at: Optional[datetime] = None  # 调度时间
    started_at: Optional[datetime] = None  # 开始时间
    completed_at: Optional[datetime] = None  # 完成时间

    # 执行参数
    parameters: Dict[str, Any] = field(default_factory=dict)  # 执行参数
    timeout: Optional[int] = None  # 超时时间(秒)
    retry_count: int = 0  # 重试次数
    max_retries: int = 3  # 最大重试次数

    # 亲和性
    user_id: Optional[str] = None  # 用户ID
    affinity_tags: Optional[List[str]] = None  # 亲和性标签

    # 结果
    result: Optional[Any] = None  # 执行结果
    error: Optional[str] = None  # 错误信息

    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, **kwargs):
        """创建新任务，自动生成ID"""
        return cls(task_id=f"task_{uuid.uuid4().hex[:8]}", submitted_at=datetime.now(), **kwargs)


@dataclass
class NodeInfo:
    """节点信息模型"""

    # 基本信息
    node_id: str  # 节点ID
    hostname: str  # 主机名
    platform: str  # 平台 (macos/windows/linux)
    arch: str  # 架构 (x64/arm64)

    # 状态信息
    status: NodeStatus = NodeStatus.OFFLINE  # 节点状态
    cpu_usage: float = 0.0  # CPU使用率 (0-100)
    memory_usage: float = 0.0  # 内存使用率 (0-100)
    disk_usage: float = 0.0  # 磁盘使用率 (0-100)

    # 能力信息
    available_skills: List[str] = field(default_factory=list)  # 可用技能列表
    max_concurrent_tasks: int = 5  # 最大并发任务数
    running_tasks: int = 0  # 当前运行任务数

    # 网络信息
    ip_address: str = ""  # IP地址
    tailscale_ip: str = ""  # Tailscale IP
    port: int = 18789  # 服务端口

    # 性能指标
    total_tasks_processed: int = 0  # 总处理任务数
    successful_tasks: int = 0  # 成功任务数
    failed_tasks: int = 0  # 失败任务数
    average_execution_time: float = 0.0  # 平均执行时间

    # 注册信息
    registered_at: Optional[datetime] = None  # 注册时间
    last_heartbeat: Optional[datetime] = None  # 最后心跳时间

    # 标签
    tags: List[str] = field(default_factory=list)  # 节点标签


@dataclass
class ClusterState:
    """集群状态"""

    # 版本信息
    version: int = 0  # 状态版本号
    updated_at: Optional[datetime] = None  # 更新时间

    # 节点信息
    nodes: Dict[str, NodeInfo] = field(default_factory=dict)  # 节点信息

    # 任务信息
    tasks: Dict[str, Task] = field(default_factory=dict)  # 任务信息

    # 统计信息
    total_nodes: int = 0  # 总节点数
    online_nodes: int = 0  # 在线节点数
    total_tasks: int = 0  # 总任务数
    running_tasks: int = 0  # 运行中任务数

    # 配置
    configuration: Dict[str, Any] = field(default_factory=dict)  # 集群配置

    def add_node(self, node: NodeInfo):
        """添加节点"""
        self.nodes[node.node_id] = node
        self.total_nodes = len(self.nodes)
        if node.status == NodeStatus.ONLINE:
            self.online_nodes += 1
        self.version += 1
        self.updated_at = datetime.now()

    def remove_node(self, node_id: str):
        """移除节点"""
        if node_id in self.nodes:
            node = self.nodes[node_id]
            if node.status == NodeStatus.ONLINE:
                self.online_nodes -= 1
            del self.nodes[node_id]
            self.total_nodes = len(self.nodes)
            self.version += 1
            self.updated_at = datetime.now()

    def update_node_status(self, node_id: str, status: NodeStatus):
        """更新节点状态"""
        if node_id in self.nodes:
            old_status = self.nodes[node_id].status
            self.nodes[node_id].status = status
            self.nodes[node_id].last_heartbeat = datetime.now()

            # 更新在线节点计数
            if old_status == NodeStatus.ONLINE and status != NodeStatus.ONLINE:
                self.online_nodes -= 1
            elif old_status != NodeStatus.ONLINE and status == NodeStatus.ONLINE:
                self.online_nodes += 1

            self.version += 1
            self.updated_at = datetime.now()

    def get_online_nodes(self) -> List[NodeInfo]:
        """获取所有在线节点"""
        return [node for node in self.nodes.values() if node.status == NodeStatus.ONLINE]

    def add_task(self, task: Task):
        """添加任务"""
        self.tasks[task.task_id] = task
        self.total_tasks = len(self.tasks)
        if task.status == TaskStatus.RUNNING:
            self.running_tasks += 1
        self.version += 1
        self.updated_at = datetime.now()
