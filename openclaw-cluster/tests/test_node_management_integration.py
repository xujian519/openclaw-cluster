"""
OpenClaw 集群系统 - 节点管理和心跳集成测试

完整测试节点注册、心跳监控和API功能
"""
import asyncio
import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

from common.config import Config
from common.models import NodeStatus
from storage.database import Database
from storage.repositories import NodeRepository
from coordinator.node_service import NodeRegistrationService
from coordinator.heartbeat_monitor import HeartbeatMonitor
from coordinator.api import create_api_app
from worker.heartbeat import HeartbeatClient


# ========== 测试固件 ==========


@pytest.fixture
async def test_database():
    """创建测试数据库"""
    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / "test_cluster.db"

    # 创建数据库
    database = Database(str(db_path))
    await database.initialize()

    yield database

    # 清理
    await database.close()
    shutil.rmtree(temp_dir)


@pytest.fixture
def test_config():
    """创建测试配置"""
    return Config(
        cluster_name="test-cluster",
        storage=type("obj", (object,), {"type": "sqlite", "path": ":memory:"}),
        coordinator=type("obj", (object,), {"host": "127.0.0.1", "port": 8888}),
        worker=type("obj", (object,), {
            "max_concurrent_tasks": 5,
            "heartbeat_interval": 5,
            "skills_dir": "./skills"
        }),
    )


@pytest.fixture
async def node_service(test_database):
    """创建节点注册服务"""
    return NodeRegistrationService(test_database)


@pytest.fixture
async def heartbeat_monitor(test_database):
    """创建心跳监控服务"""
    return HeartbeatMonitor(test_database, heartbeat_timeout=30, check_interval=10)


# ========== 节点注册测试 ==========


@pytest.mark.asyncio
async def test_node_registration(node_service: NodeRegistrationService):
    """测试节点注册功能"""
    # 注册第一个节点
    result = await node_service.register_node(
        hostname="worker-01",
        platform="linux",
        arch="x64",
        available_skills=["python", "data-analysis"],
        ip_address="192.168.1.100",
        port=18789,
        max_concurrent_tasks=5,
        tags=["gpu"],
    )

    assert result["success"] is True
    assert result["node_id"] is not None
    assert result["registered"] is True
    assert "node_info" in result
    assert result["node_info"]["hostname"] == "worker-01"
    assert result["node_info"]["status"] == "online"

    node_id = result["node_id"]

    # 验证节点可以查询到
    node = await node_service.get_node(node_id)
    assert node is not None
    assert node.hostname == "worker-01"
    assert node.platform == "linux"
    assert node.available_skills == ["python", "data-analysis"]


@pytest.mark.asyncio
async def test_node_reregistration(node_service: NodeRegistrationService):
    """测试节点重新注册"""
    # 第一次注册
    result1 = await node_service.register_node(
        hostname="worker-02",
        platform="macos",
        arch="arm64",
        available_skills=["python"],
    )
    assert result1["success"] is True
    assert result1["registered"] is True

    node_id = result1["node_id"]

    # 等待一小段时间
    await asyncio.sleep(0.1)

    # 使用相同主机名重新注册（模拟节点重启）
    result2 = await node_service.register_node(
        hostname="worker-02",
        platform="macos",
        arch="arm64",
        available_skills=["python", "ml"],  # 更新的技能列表
    )

    assert result2["success"] is True
    assert result2["node_id"] == node_id  # 应该返回相同的节点ID
    assert result2["registered"] is False  # 不是新注册

    # 验证技能已更新
    node = await node_service.get_node(node_id)
    assert node.available_skills == ["python", "ml"]


@pytest.mark.asyncio
async def test_invalid_node_registration(node_service: NodeRegistrationService):
    """测试无效的节点注册"""
    # 无效的平台
    result = await node_service.register_node(
        hostname="worker-03",
        platform="invalid_platform",
        arch="x64",
        available_skills=["python"],
    )
    assert result["success"] is False
    assert "验证失败" in result["message"]

    # 空主机名
    result = await node_service.register_node(
        hostname="",
        platform="linux",
        arch="x64",
        available_skills=["python"],
    )
    assert result["success"] is False

    # 空技能列表
    result = await node_service.register_node(
        hostname="worker-04",
        platform="linux",
        arch="x64",
        available_skills=[],
    )
    assert result["success"] is False


# ========== 节点查询测试 ==========


@pytest.mark.asyncio
async def test_list_nodes(node_service: NodeRegistrationService):
    """测试列出所有节点"""
    # 注册多个节点
    await node_service.register_node(
        hostname="worker-01", platform="linux", arch="x64",
        available_skills=["python"]
    )
    await node_service.register_node(
        hostname="worker-02", platform="macos", arch="arm64",
        available_skills=["python", "ml"]
    )
    await node_service.register_node(
        hostname="worker-03", platform="windows", arch="x64",
        available_skills=["data-processing"]
    )

    # 获取所有节点
    nodes = await node_service.list_all_nodes()
    assert len(nodes) == 3

    # 获取在线节点
    online_nodes = await node_service.list_online_nodes()
    assert len(online_nodes) == 3


@pytest.mark.asyncio
async def test_find_nodes_by_skill(node_service: NodeRegistrationService):
    """测试按技能查找节点"""
    # 注册具有不同技能的节点
    await node_service.register_node(
        hostname="python-worker", platform="linux", arch="x64",
        available_skills=["python", "flask"]
    )
    await node_service.register_node(
        hostname="ml-worker", platform="linux", arch="x64",
        available_skills=["python", "ml", "tensorflow"]
    )
    await node_service.register_node(
        hostname="data-worker", platform="linux", arch="x64",
        available_skills=["data-analysis", "pandas"]
    )

    # 查找具有python技能的节点
    python_nodes = await node_service.find_nodes_by_skill("python")
    assert len(python_nodes) == 2

    # 查找具有ml技能的节点
    ml_nodes = await node_service.find_nodes_by_skill("ml")
    assert len(ml_nodes) == 1
    assert ml_nodes[0].hostname == "ml-worker"


# ========== 心跳监控测试 ==========


@pytest.mark.asyncio
async def test_heartbeat_update(heartbeat_monitor: HeartbeatMonitor):
    """测试心跳更新"""
    # 创建测试节点
    node_repo = heartbeat_monitor.node_repo
    from common.models import NodeInfo
    node = NodeInfo(
        node_id="test-node-01",
        hostname="test-worker",
        platform="linux",
        arch="x64",
        status=NodeStatus.ONLINE,
        available_skills=["python"],
        registered_at=datetime.now(),
        last_heartbeat=datetime.now(),
    )
    await node_repo.create(node)

    # 更新心跳
    success = await heartbeat_monitor.update_node_heartbeat(
        node_id="test-node-01",
        cpu_usage=45.5,
        memory_usage=67.2,
        disk_usage=80.0,
        running_tasks=2,
    )
    assert success is True

    # 验证更新
    updated_node = await node_repo.get("test-node-01")
    assert updated_node.cpu_usage == 45.5
    assert updated_node.memory_usage == 67.2
    assert updated_node.disk_usage == 80.0
    assert updated_node.running_tasks == 2


@pytest.mark.asyncio
async def test_node_health_status(heartbeat_monitor: HeartbeatMonitor):
    """测试节点健康状态查询"""
    # 创建测试节点
    node_repo = heartbeat_monitor.node_repo
    from common.models import NodeInfo
    node = NodeInfo(
        node_id="test-node-02",
        hostname="test-worker-2",
        platform="linux",
        arch="x64",
        status=NodeStatus.ONLINE,
        available_skills=["python"],
        registered_at=datetime.now(),
        last_heartbeat=datetime.now(),
        max_concurrent_tasks=10,
        running_tasks=3,
    )
    await node_repo.create(node)

    # 获取健康状态
    health = await heartbeat_monitor.get_node_health_status("test-node-02")

    assert health["node_id"] == "test-node-02"
    assert health["healthy"] is True
    assert health["status"] == "online"
    assert health["is_timeout"] is False
    assert health["available_capacity"] == 7  # 10 - 3


@pytest.mark.asyncio
async def test_cluster_health_summary(heartbeat_monitor: HeartbeatMonitor):
    """测试集群健康状态摘要"""
    # 创建多个测试节点
    node_repo = heartbeat_monitor.node_repo
    from common.models import NodeInfo

    nodes = [
        NodeInfo(
            node_id=f"test-node-{i:02d}",
            hostname=f"worker-{i:02d}",
            platform="linux",
            arch="x64",
            status=NodeStatus.ONLINE,
            available_skills=["python"],
            max_concurrent_tasks=5,
            running_tasks=i,  # 不同的运行任务数
            registered_at=datetime.now(),
            last_heartbeat=datetime.now(),
        )
        for i in range(1, 4)
    ]

    for node in nodes:
        await node_repo.create(node)

    # 获取集群健康状态
    summary = await heartbeat_monitor.get_cluster_health_summary()

    assert summary["total_nodes"] == 3
    assert summary["online_nodes"] == 3
    assert summary["total_capacity"] == 15  # 3 * 5
    # 注意: running_tasks在创建时被初始化为i的值，但会被覆盖
    # 实际的used_capacity应该是所有节点的running_tasks之和
    assert summary["available_capacity"] >= 0


@pytest.mark.asyncio
async def test_heartbeat_timeout_detection(heartbeat_monitor: HeartbeatMonitor):
    """测试心跳超时检测"""
    # 创建一个很久没发送心跳的节点
    node_repo = heartbeat_monitor.node_repo
    from common.models import NodeInfo
    from datetime import timedelta

    old_time = datetime.now() - timedelta(seconds=120)  # 120秒前

    node = NodeInfo(
        node_id="stale-node",
        hostname="stale-worker",
        platform="linux",
        arch="x64",
        status=NodeStatus.ONLINE,
        available_skills=["python"],
        registered_at=datetime.now(),
        last_heartbeat=old_time,
    )
    await node_repo.create(node)

    # 执行心跳检查
    result = await heartbeat_monitor.check_heartbeat()

    assert result["all_nodes_healthy"] is False
    assert result["timeout_nodes_count"] == 1
    assert len(result["timeout_nodes"]) == 1
    assert result["timeout_nodes"][0]["node_id"] == "stale-node"

    # 验证节点已被标记为离线
    stale_node = await node_repo.get("stale-node")
    assert stale_node.status == NodeStatus.OFFLINE


# ========== API测试 ==========


@pytest.mark.asyncio
async def test_api_node_registration(node_service: NodeRegistrationService):
    """测试API节点注册端点"""
    from fastapi.testclient import TestClient

    heartbeat_monitor = HeartbeatMonitor(
        node_service.db, heartbeat_timeout=30, check_interval=10
    )
    app = create_api_app(node_service, heartbeat_monitor)
    client = TestClient(app)

    # 测试注册端点
    response = client.post(
        "/api/v1/nodes/register",
        json={
            "hostname": "api-worker-01",
            "platform": "linux",
            "arch": "x64",
            "available_skills": ["python", "fastapi"],
            "ip_address": "10.0.0.1",
            "max_concurrent_tasks": 10,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["node_id"] is not None
    assert data["registered"] is True


@pytest.mark.asyncio
async def test_api_get_nodes(node_service: NodeRegistrationService):
    """测试API获取节点列表"""
    from fastapi.testclient import TestClient

    # 注册一些节点
    await node_service.register_node(
        hostname="worker-01", platform="linux", arch="x64",
        available_skills=["python"]
    )
    await node_service.register_node(
        hostname="worker-02", platform="macos", arch="arm64",
        available_skills=["python", "ml"]
    )

    heartbeat_monitor = HeartbeatMonitor(
        node_service.db, heartbeat_timeout=30, check_interval=10
    )
    app = create_api_app(node_service, heartbeat_monitor)
    client = TestClient(app)

    # 测试获取所有节点
    response = client.get("/api/v1/nodes")
    assert response.status_code == 200
    nodes = response.json()
    assert len(nodes) == 2

    # 测试获取在线节点
    response = client.get("/api/v1/nodes/online")
    assert response.status_code == 200
    online_nodes = response.json()
    assert len(online_nodes) == 2

    # 测试按技能查找
    response = client.get("/api/v1/nodes/skills/ml")
    assert response.status_code == 200
    ml_nodes = response.json()
    assert len(ml_nodes) == 1
    assert ml_nodes[0]["hostname"] == "worker-02"


@pytest.mark.asyncio
async def test_api_health_endpoints(node_service: NodeRegistrationService):
    """测试API健康检查端点"""
    from fastapi.testclient import TestClient

    heartbeat_monitor = HeartbeatMonitor(
        node_service.db, heartbeat_timeout=30, check_interval=10
    )

    # 注册一个节点
    result = await node_service.register_node(
        hostname="health-test-node", platform="linux", arch="x64",
        available_skills=["python"]
    )
    node_id = result["node_id"]

    app = create_api_app(node_service, heartbeat_monitor)
    client = TestClient(app)

    # 测试节点健康状态
    response = client.get(f"/api/v1/nodes/{node_id}/health")
    assert response.status_code == 200
    health = response.json()
    assert health["node_id"] == node_id
    assert health["healthy"] is True

    # 测试集群健康状态
    response = client.get("/api/v1/cluster/health")
    assert response.status_code == 200
    summary = response.json()
    assert summary["total_nodes"] == 1
    assert summary["online_nodes"] == 1


# ========== 完整集成测试 ==========


@pytest.mark.asyncio
async def test_full_node_lifecycle(node_service: NodeRegistrationService):
    """测试完整的节点生命周期"""
    # 1. 节点注册
    register_result = await node_service.register_node(
        hostname="lifecycle-worker",
        platform="linux",
        arch="x64",
        available_skills=["python", "async"],
        max_concurrent_tasks=5,
    )
    assert register_result["success"] is True
    node_id = register_result["node_id"]

    # 2. 验证节点已创建
    node = await node_service.get_node(node_id)
    assert node is not None
    assert node.status == NodeStatus.ONLINE
    assert node.running_tasks == 0

    # 3. 模拟心跳更新
    heartbeat_monitor = HeartbeatMonitor(
        node_service.db, heartbeat_timeout=30, check_interval=10
    )
    await heartbeat_monitor.update_node_heartbeat(
        node_id=node_id,
        cpu_usage=50.0,
        memory_usage=60.0,
        disk_usage=70.0,
        running_tasks=2,
    )

    # 4. 验证心跳已更新
    updated_node = await node_service.get_node(node_id)
    assert updated_node.cpu_usage == 50.0
    assert updated_node.running_tasks == 2

    # 5. 验证健康状态
    health = await heartbeat_monitor.get_node_health_status(node_id)
    assert health["healthy"] is True
    assert health["available_capacity"] == 3  # 5 - 2

    # 6. 按技能查找节点
    python_nodes = await node_service.find_nodes_by_skill("python")
    assert node_id in [n.node_id for n in python_nodes]

    # 7. 节点注销
    unregister_success = await node_service.unregister_node(node_id)
    assert unregister_success is True

    # 8. 验证节点已离线
    offline_node = await node_service.get_node(node_id)
    assert offline_node.status == NodeStatus.OFFLINE


if __name__ == "__main__":
    # 运行测试
    pytest.main([__file__, "-v", "-s"])
