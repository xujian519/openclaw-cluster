"""
OpenClaw 集群系统 - 配置管理

提供配置加载和验证功能
"""
import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, field


@dataclass
class NATSConfig:
    """NATS 配置"""
    url: str = "nats://localhost:4222"
    jetstream_enabled: bool = True
    max_reconnect: int = 10
    reconnect_wait: int = 2
    timeout: float = 5.0


@dataclass
class StorageConfig:
    """存储配置"""
    type: str = "sqlite"  # sqlite or etcd
    path: str = "./data/cluster.db"
    pool_size: int = 5


@dataclass
class CoordinatorConfig:
    """主节点配置"""
    host: str = "0.0.0.0"
    port: int = 8080
    workers: int = 4


@dataclass
class WorkerConfig:
    """工作节点配置"""
    max_concurrent_tasks: int = 5
    heartbeat_interval: int = 30
    skills_dir: str = "./skills"


@dataclass
class LoggingConfig:
    """日志配置"""
    level: str = "INFO"
    format: str = "json"
    output: str = "./logs"


@dataclass
class Config:
    """总配置"""
    # 组件配置
    nats: NATSConfig = field(default_factory=NATSConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    coordinator: CoordinatorConfig = field(default_factory=CoordinatorConfig)
    worker: WorkerConfig = field(default_factory=WorkerConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    # 集群配置
    cluster_name: str = "openclaw-cluster"
    node_id: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Config":
        """从字典创建配置"""
        config = cls()

        if "nats" in data:
            config.nats = NATSConfig(**data["nats"])
        if "storage" in data:
            config.storage = StorageConfig(**data["storage"])
        if "coordinator" in data:
            config.coordinator = CoordinatorConfig(**data["coordinator"])
        if "worker" in data:
            config.worker = WorkerConfig(**data["worker"])
        if "logging" in data:
            config.logging = LoggingConfig(**data["logging"])

        if "cluster_name" in data:
            config.cluster_name = data["cluster_name"]
        if "node_id" in data:
            config.node_id = data["node_id"]

        return config

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "cluster_name": self.cluster_name,
            "node_id": self.node_id,
            "nats": self.nats.__dict__,
            "storage": self.storage.__dict__,
            "coordinator": self.coordinator.__dict__,
            "worker": self.worker.__dict__,
            "logging": self.logging.__dict__,
        }


def load_config(config_path: str) -> Config:
    """
    加载配置文件

    Args:
        config_path: 配置文件路径

    Returns:
        配置对象
    """
    path = Path(config_path)

    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return Config.from_dict(data)


def load_config_from_env() -> Config:
    """从环境变量加载配置"""
    config = Config()

    # NATS 配置
    if nats_url := os.getenv("NATS_URL"):
        config.nats.url = nats_url

    # 存储配置
    if storage_path := os.getenv("STORAGE_PATH"):
        config.storage.path = storage_path

    # 节点ID
    if node_id := os.getenv("NODE_ID"):
        config.node_id = node_id

    return config


def save_config(config: Config, config_path: str):
    """
    保存配置到文件

    Args:
        config: 配置对象
        config_path: 配置文件路径
    """
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config.to_dict(), f, default_flow_style=False)
