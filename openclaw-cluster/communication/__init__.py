"""
OpenClaw 集群系统 - 通信模块

提供基于 NATS 的消息通信功能
"""

from .messages import (
    Message,
    MessageType,
    NodeHeartbeatMessage,
    TaskAssignMessage,
    TaskResultMessage,
)
from .nats_client import NATSClient

__all__ = [
    "NATSClient",
    "Message",
    "MessageType",
    "NodeHeartbeatMessage",
    "TaskAssignMessage",
    "TaskResultMessage",
]
