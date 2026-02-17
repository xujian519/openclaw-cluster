"""
OpenClaw 集群系统 - 消息定义

定义系统中使用的所有消息类型
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class MessageType(Enum):
    """消息类型"""

    # 节点管理
    NODE_REGISTER = "node.register"
    NODE_HEARTBEAT = "node.heartbeat"
    NODE_SHUTDOWN = "node.shutdown"

    # 任务管理
    TASK_SUBMIT = "task.submit"
    TASK_ASSIGN = "task.assign"
    TASK_START = "task.start"
    TASK_PROGRESS = "task.progress"
    TASK_COMPLETE = "task.complete"
    TASK_FAIL = "task.fail"

    # 技能管理
    SKILL_REGISTER = "skill.register"
    SKILL_LOAD = "skill.load"
    SKILL_UNLOAD = "skill.unload"

    # 状态同步
    STATE_SYNC = "state.sync"
    STATE_UPDATE = "state.update"


@dataclass
class Message:
    """基础消息"""

    type: MessageType
    timestamp: datetime
    sender_id: str
    payload: Dict[str, Any] = field(default_factory=dict)
    receiver_id: Optional[str] = None

    def to_json(self) -> str:
        """转换为 JSON"""
        data = {
            "type": self.type.value,
            "timestamp": self.timestamp.isoformat(),
            "sender_id": self.sender_id,
            "payload": self.payload,
        }
        if self.receiver_id:
            data["receiver_id"] = self.receiver_id
        return json.dumps(data)

    @classmethod
    def from_json(cls, json_str: str) -> "Message":
        """从 JSON 创建"""
        data = json.loads(json_str)
        return cls(
            type=MessageType(data["type"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            sender_id=data["sender_id"],
            receiver_id=data.get("receiver_id"),
            payload=data.get("payload", {}),
        )


@dataclass
class NodeHeartbeatMessage:
    """节点心跳消息"""

    sender_id: str
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    running_tasks: int = 0
    status: str = "online"
    timestamp: datetime = field(default_factory=datetime.now)

    def to_json(self) -> str:
        """转换为 JSON"""
        data = {
            "sender_id": self.sender_id,
            "cpu_usage": self.cpu_usage,
            "memory_usage": self.memory_usage,
            "running_tasks": self.running_tasks,
            "status": self.status,
            "timestamp": self.timestamp.isoformat(),
        }
        return json.dumps(data)


@dataclass
class TaskAssignMessage:
    """任务分配消息"""

    task_id: str
    task_type: str
    required_skills: list
    parameters: Dict[str, Any]
    sender_id: str
    timeout: Optional[int] = None
    receiver_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_json(self) -> str:
        """转换为 JSON"""
        data = {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "required_skills": self.required_skills,
            "parameters": self.parameters,
            "sender_id": self.sender_id,
            "timeout": self.timeout,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.receiver_id:
            data["receiver_id"] = self.receiver_id
        return json.dumps(data)


@dataclass
class TaskResultMessage:
    """任务结果消息"""

    task_id: str
    success: bool
    sender_id: str
    result: Optional[Any] = None
    error: Optional[str] = None
    execution_time: float = 0.0
    receiver_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_json(self) -> str:
        """转换为 JSON"""
        data = {
            "task_id": self.task_id,
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "execution_time": self.execution_time,
            "sender_id": self.sender_id,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.receiver_id:
            data["receiver_id"] = self.receiver_id
        return json.dumps(data)
