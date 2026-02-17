"""
OpenClaw 集群系统 - 主节点模块

提供集群协调、任务调度和状态管理功能
"""

from .main import Coordinator, create_coordinator

__all__ = [
    "Coordinator",
    "create_coordinator",
]
