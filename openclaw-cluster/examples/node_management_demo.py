#!/usr/bin/env python3
"""
OpenClaw 集群系统 - 节点管理和心跳机制演示

展示完整的节点注册、心跳监控和API管理功能
"""

import asyncio
import shutil
import tempfile
from pathlib import Path

from coordinator.api import create_api_app
from coordinator.heartbeat_monitor import HeartbeatMonitor
from coordinator.node_service import NodeRegistrationService
from storage.database import Database
from worker.heartbeat import HeartbeatClient


async def demo_coordinator():
    """演示协调器功能"""
    print("\n" + "=" * 60)
    print("OpenClaw 集群系统 - 节点管理和心跳机制演示")
    print("=" * 60)

    # 创建临时数据库
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / "demo_cluster.db"
    database = Database(str(db_path))
    await database.initialize()
    print(f"\n✓ 数据库初始化完成: {db_path}")

    # 创建服务
    node_service = NodeRegistrationService(database)
    heartbeat_monitor = HeartbeatMonitor(database, heartbeat_timeout=30, check_interval=10)

    print("\n" + "-" * 60)
    print("1. 节点注册演示")
    print("-" * 60)

    # 注册多个工作节点
    nodes_to_register = [
        {
            "hostname": "worker-python-01",
            "platform": "linux",
            "arch": "x64",
            "skills": ["python", "fastapi", "asyncio"],
            "tags": ["gpu", "high-memory"],
        },
        {
            "hostname": "worker-ml-01",
            "platform": "linux",
            "arch": "x64",
            "skills": ["python", "tensorflow", "pytorch"],
            "tags": ["gpu", "ml"],
        },
        {
            "hostname": "worker-data-01",
            "platform": "macos",
            "arch": "arm64",
            "skills": ["python", "pandas", "numpy"],
            "tags": ["data-processing"],
        },
    ]

    registered_nodes = []
    for node_config in nodes_to_register:
        result = await node_service.register_node(
            hostname=node_config["hostname"],
            platform=node_config["platform"],
            arch=node_config["arch"],
            available_skills=node_config["skills"],
            tags=node_config["tags"],
            max_concurrent_tasks=5,
        )

        if result["success"]:
            print(f"  ✓ 节点注册成功: {result['node_id']}")
            print(f"    - 主机名: {node_config['hostname']}")
            print(f"    - 技能: {', '.join(node_config['skills'])}")
            print(f"    - 标签: {', '.join(node_config['tags'])}")
            registered_nodes.append(result["node_id"])

    print("\n" + "-" * 60)
    print("2. 节点查询演示")
    print("-" * 60)

    # 获取所有节点
    all_nodes = await node_service.list_all_nodes()
    print(f"  总节点数: {len(all_nodes)}")

    # 获取在线节点
    online_nodes = await node_service.list_online_nodes()
    print(f"  在线节点数: {len(online_nodes)}")

    # 按技能查找节点
    python_nodes = await node_service.find_nodes_by_skill("python")
    print(f"  具有Python技能的节点: {len(python_nodes)}")

    ml_nodes = await node_service.find_nodes_by_skill("tensorflow")
    print(f"  具有TensorFlow技能的节点: {len(ml_nodes)}")

    print("\n" + "-" * 60)
    print("3. 心跳更新演示")
    print("-" * 60)

    # 模拟节点发送心跳
    for i, node_id in enumerate(registered_nodes):
        await heartbeat_monitor.update_node_heartbeat(
            node_id=node_id,
            cpu_usage=20.0 + i * 10,
            memory_usage=40.0 + i * 5,
            disk_usage=60.0 + i * 2,
            running_tasks=i,
        )
        print(f"  ✓ 节点 {node_id} 心跳更新成功")

    print("\n" + "-" * 60)
    print("4. 健康状态查询演示")
    print("-" * 60)

    # 查询节点健康状态
    for node_id in registered_nodes[:2]:  # 只查询前两个
        health = await heartbeat_monitor.get_node_health_status(node_id)
        print(f"  节点: {node_id}")
        print(f"    - 健康状态: {'✓ 健康' if health['healthy'] else '✗ 不健康'}")
        print(f"    - 状态: {health['status']}")
        print(f"    - CPU使用率: {health['cpu_usage']}%")
        print(f"    - 内存使用率: {health['memory_usage']}%")
        print(f"    - 运行任务数: {health['running_tasks']}")
        print(f"    - 可用容量: {health['available_capacity']}")

    # 查询集群健康状态
    cluster_health = await heartbeat_monitor.get_cluster_health_summary()
    print("\n  集群健康状态:")
    print(f"    - 总节点数: {cluster_health['total_nodes']}")
    print(f"    - 在线节点: {cluster_health['online_nodes']}")
    print(f"    - 总容量: {cluster_health['total_capacity']}")
    print(f"    - 已用容量: {cluster_health['used_capacity']}")
    print(f"    - 容量利用率: {cluster_health['capacity_utilization']:.1f}%")

    print("\n" + "-" * 60)
    print("5. 启动API服务器演示")
    print("-" * 60)

    # 创建FastAPI应用
    app = create_api_app(node_service, heartbeat_monitor)

    # 打印可用路由
    print("\n  可用的API端点:")
    for route in app.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            if route.path.startswith("/api/v1"):
                methods = ", ".join(sorted(route.methods))
                print(f"    {methods:8} {route.path}")

    print("\n" + "-" * 60)
    print("6. API测试演示（使用TestClient）")
    print("-" * 60)

    from fastapi.testclient import TestClient

    client = TestClient(app)

    # 测试健康检查
    response = client.get("/health")
    print("\n  GET /health")
    print(f"    状态码: {response.status_code}")
    print(f"    响应: {response.json()}")

    # 测试获取所有节点
    response = client.get("/api/v1/nodes")
    print("\n  GET /api/v1/nodes")
    print(f"    状态码: {response.status_code}")
    nodes = response.json()
    print(f"    返回节点数: {len(nodes)}")

    # 测试获取在线节点
    response = client.get("/api/v1/nodes/online")
    print("\n  GET /api/v1/nodes/online")
    print(f"    状态码: {response.status_code}")
    online = response.json()
    print(f"    在线节点数: {len(online)}")

    # 测试按技能查找
    response = client.get("/api/v1/nodes/skills/python")
    print("\n  GET /api/v1/nodes/skills/python")
    print(f"    状态码: {response.status_code}")
    python_nodes = response.json()
    print(f"    Python节点数: {len(python_nodes)}")

    # 测试集群健康状态
    response = client.get("/api/v1/cluster/health")
    print("\n  GET /api/v1/cluster/health")
    print(f"    状态码: {response.status_code}")
    health_summary = response.json()
    print("    集群状态:")
    print(f"      - 总节点: {health_summary['total_nodes']}")
    print(f"      - 在线: {health_summary['online_nodes']}")
    print(f"      - 容量利用率: {health_summary['capacity_utilization']:.1f}%")

    print("\n" + "-" * 60)
    print("7. 心跳监控演示")
    print("-" * 60)

    # 启动心跳监控
    await heartbeat_monitor.start()
    print("  ✓ 心跳监控已启动")

    # 等待一段时间观察心跳检查
    print("\n  等待心跳检查（2秒）...")
    await asyncio.sleep(2)

    # 手动执行心跳检查
    check_result = await heartbeat_monitor.check_heartbeat()
    print("  ✓ 心跳检查完成")
    print(f"    - 超时节点数: {check_result['timeout_nodes_count']}")
    print(f"    - 所有节点健康: {'是' if check_result['all_nodes_healthy'] else '否'}")

    # 停止心跳监控
    await heartbeat_monitor.stop()
    print("  ✓ 心跳监控已停止")

    print("\n" + "-" * 60)
    print("8. 节点生命周期管理演示")
    print("-" * 60)

    # 获取一个节点的详细信息
    node_id = registered_nodes[0]
    node = await node_service.get_node(node_id)
    print(f"\n  节点详情 ({node_id}):")
    print(f"    - 主机名: {node.hostname}")
    print(f"    - 平台: {node.platform}")
    print(f"    - 架构: {node.arch}")
    print(f"    - 状态: {node.status.value}")
    print(f"    - 注册时间: {node.registered_at}")
    print(f"    - 最后心跳: {node.last_heartbeat}")

    # 注销节点
    success = await node_service.unregister_node(node_id)
    if success:
        print(f"\n  ✓ 节点 {node_id} 已注销")

        # 验证节点状态
        offline_node = await node_service.get_node(node_id)
        print(f"    - 新状态: {offline_node.status.value}")

    print("\n" + "=" * 60)
    print("演示完成！")
    print("=" * 60)

    # 清理
    await database.close()
    shutil.rmtree(temp_dir)
    print("\n✓ 临时文件已清理")


async def demo_worker_client():
    """演示工作节点客户端功能"""
    print("\n" + "=" * 60)
    print("工作节点心跳客户端演示")
    print("=" * 60)

    # 创建测试配置
    class TestConfig:
        class Worker:
            heartbeat_interval = 5
            max_concurrent_tasks = 5

        worker = Worker()

    config = TestConfig()
    coordinator_url = "http://localhost:8888"

    # 创建心跳客户端（不实际启动，只展示功能）
    print("\n创建心跳客户端:")
    print(f"  - 协调器URL: {coordinator_url}")
    print(f"  - 心跳间隔: {config.worker.heartbeat_interval}秒")
    print(f"  - 最大并发任务: {config.worker.max_concurrent_tasks}")

    client = HeartbeatClient(
        config=config,
        coordinator_url=coordinator_url,
        node_id="demo-worker-001",
        available_skills=["python", "demo"],
    )

    print("\n✓ 心跳客户端创建成功")
    print(f"  - 节点ID: {client.node_id}")
    print(f"  - 系统信息: {client.system_info}")

    print("\n" + "=" * 60)


def main():
    """主函数"""
    asyncio.run(demo_coordinator())
    asyncio.run(demo_worker_client())


if __name__ == "__main__":
    main()
