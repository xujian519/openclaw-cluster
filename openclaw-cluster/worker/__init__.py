"""
OpenClaw 集群系统 - 工作节点模块

提供任务执行、技能调用和节点注册功能
"""

from .main import Worker, create_worker

__all__ = [
    "Worker",
    "create_worker",
]
