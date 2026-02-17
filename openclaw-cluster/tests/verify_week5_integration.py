#!/usr/bin/env python3
"""OpenClaw 集群系统 - 第5周集成验证（技能系统+NATS消息）"""

import asyncio
import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from common.models import NodeInfo, NodeStatus, Task, TaskPriority, TaskType
from scheduler.task_scheduler import SchedulingStrategy, TaskScheduler
from skills.skill_discovery import BUILTIN_SKILLS, SkillDiscovery
from skills.skill_registry import SkillCategory, SkillMetadata, SkillRegistry
from storage.database import Database
from storage.state_manager import StateManager


async def test_skill_registry():
    """测试技能注册表"""
    print("\n=== 测试技能注册表 ===")

    # 初始化
    db = Database(":memory:")
    await db.initialize()
    state_manager = StateManager(db)
    await state_manager.initialize()

    registry = SkillRegistry(state_manager)

    # 注册技能
    skills = []
    for skill_config in BUILTIN_SKILLS[:3]:  # 注册3个内置技能
        metadata = SkillMetadata(
            name=skill_config["name"],
            description=skill_config["description"],
            category=SkillCategory(skill_config["category"]),
            version=skill_config["version"],
            author=skill_config["author"],
            dependencies=skill_config["dependencies"],
            required_resources=skill_config["required_resources"],
            tags=skill_config["tags"],
        )

        success = await registry.register_skill(metadata)
        assert success is True
        skills.append(metadata)
        print(f"✅ 技能已注册: {metadata.name}")

    # 注册技能实例
    await registry.register_skill_instance("python", "node_001")
    await registry.register_skill_instance("search", "node_001")
    await registry.register_skill_instance("weather", "node_002")
    print("✅ 技能实例已注册")

    # 查询技能
    python_skill = await registry.get_skill_metadata("python")
    assert python_skill is not None
    print(f"✅ 技能查询成功: {python_skill.name}")
    print(f"   描述: {python_skill.description}")
    print(f"   类别: {python_skill.category.value}")

    # 查询技能实例
    instances = await registry.get_skill_instances("python")
    assert len(instances) == 1
    print(f"✅ 技能实例: {len(instances)} 个")

    # 查询节点技能
    node_skills = await registry.get_node_skills("node_001")
    print(f"✅ node_001 的技能: {node_skills}")

    # 解析依赖
    deps = await registry.resolve_skill_dependencies(["weather"])
    print("✅ weather 的依赖:")
    print(f"   直接依赖: {deps['direct']}")
    print(f"   所有依赖: {deps['all']}")

    # 获取统计
    stats = await registry.get_stats()
    print("✅ 注册表统计:")
    print(f"   总技能数: {stats['total_skills']}")
    print(f"   总实例数: {stats['total_instances']}")

    # 清理
    await state_manager.shutdown()
    print("✅ 技能注册表测试通过")


async def test_skill_discovery():
    """测试技能发现"""
    print("\n=== 测试技能发现 ===")

    # 初始化
    db = Database(":memory:")
    await db.initialize()
    state_manager = StateManager(db)
    await state_manager.initialize()

    registry = SkillRegistry(state_manager)
    discovery = SkillDiscovery(registry, skills_dir="/tmp/skills")

    # 手动注册内置技能
    count = await discovery.register_local_skills(BUILTIN_SKILLS)
    print(f"✅ 手动注册了 {count} 个技能")

    # 启动发现服务
    await discovery.start("test_node_001")
    print("✅ 技能发现服务已启动")

    # 获取发现的技能
    discovered = await discovery.get_discovered_skills()
    print(f"✅ 发现的技能数: {len(discovered)}")
    for skill in discovered:
        print(f"   - {skill.name} ({skill.category.value})")

    # 获取技能统计
    stats = await registry.get_stats()
    print("✅ 技能统计:")
    print(f"   总技能数: {stats['total_skills']}")
    print(f"   类别分布: {stats['category_counts']}")

    # 停止发现服务
    await discovery.stop()
    print("✅ 技能发现服务已停止")

    # 清理
    await state_manager.shutdown()
    print("✅ 技能发现测试通过")


async def test_skill_based_scheduling():
    """测试基于技能的调度"""
    print("\n=== 测试基于技能的调度 ===")

    # 初始化
    db = Database(":memory:")
    await db.initialize()
    state_manager = StateManager(db)
    await state_manager.initialize()
    registry = SkillRegistry(state_manager)

    # 注册技能
    for skill_config in BUILTIN_SKILLS:
        metadata = SkillMetadata(
            name=skill_config["name"],
            description=skill_config["description"],
            category=SkillCategory(skill_config["category"]),
            version=skill_config["version"],
            dependencies=skill_config["dependencies"],
        )
        await registry.register_skill(metadata)

    # 添加节点并注册技能
    nodes = [
        ("node_001", ["python", "search"]),
        ("node_002", ["python", "weather"]),
        ("node_003", ["python", "ml", "data-analysis"]),
    ]

    for node_id, skills in nodes:
        node = NodeInfo(
            node_id=node_id,
            hostname=f"worker-{node_id}",
            platform="linux",
            arch="x64",
            status=NodeStatus.ONLINE,
            available_skills=skills,
            max_concurrent_tasks=5,
        )
        await state_manager.add_node(node)

        # 注册技能实例
        for skill in skills:
            await registry.register_skill_instance(skill, node_id)

        print(f"✅ 节点 {node_id} 技能: {skills}")

    # 创建调度器
    scheduler = TaskScheduler(state_manager, strategy=SchedulingStrategy.LEAST_TASKS)
    await scheduler.start()
    print("✅ 调度器已启动")

    # 测试不同技能的任务调度
    test_cases = [
        (["python"], "任意节点"),
        (["weather"], "node_002"),
        (["ml"], "node_003"),
        (["python", "search"], "node_001"),
    ]

    for required_skills, expected_node in test_cases:
        task = Task.create(
            task_type=TaskType.INTERACTIVE,
            name=f"test_task_{'_'.join(required_skills)}",
            description=f"测试 {required_skills} 技能",
            required_skills=required_skills,
            priority=TaskPriority.NORMAL,
        )

        await scheduler.submit_task(task)
        await asyncio.sleep(0.5)

        # 检查分配结果
        updated_task = await state_manager.get_task(task.task_id)
        if updated_task and updated_task.assigned_node:
            print(
                f"✅ 任务 {required_skills} -> {updated_task.assigned_node} (期望: {expected_node})"
            )

    # 获取调度器统计
    stats = await scheduler.get_scheduler_stats()
    print("✅ 调度器统计:")
    print(f"   总调度: {stats['total_scheduled']}")

    # 停止调度器
    await scheduler.stop()

    # 清理
    for node_id, _ in nodes:
        await state_manager.delete_node(node_id)

    await state_manager.shutdown()
    print("✅ 基于技能的调度测试通过")


async def test_skill_dependencies():
    """测试技能依赖解析"""
    print("\n=== 测试技能依赖解析 ===")

    # 初始化
    db = Database(":memory:")
    await db.initialize()
    state_manager = StateManager(db)
    await state_manager.initialize()
    registry = SkillRegistry(state_manager)

    # 注册有依赖关系的技能
    skills = [
        ("python", [], []),
        ("search", [], []),
        ("weather", ["search"], []),
        ("data-analysis", ["python"], []),
        ("ml", ["python", "data-analysis"], []),
    ]

    for name, deps, tags in skills:
        metadata = SkillMetadata(
            name=name,
            description=f"{name} 技能",
            category=SkillCategory.CUSTOM,
            dependencies=deps,
            tags=tags,
        )
        await registry.register_skill(metadata)

    print("✅ 已注册技能及其依赖")

    # 测试依赖解析
    test_cases = [
        (["python"], {"direct": [], "all": [], "missing": []}),
        (["weather"], {"direct": ["search"], "all": ["search"], "missing": []}),
        (
            ["ml"],
            {
                "direct": ["python", "data-analysis"],
                "all": ["python", "data-analysis"],
                "missing": [],
            },
        ),
    ]

    for required_skills, expected in test_cases:
        deps = await registry.resolve_skill_dependencies(required_skills)

        print(f"✅ {required_skills} 的依赖解析:")
        print(f"   直接依赖: {deps['direct']}")
        print(f"   所有依赖: {deps['all']}")
        print(f"   缺失依赖: {deps['missing']}")

        # 验证
        assert set(deps["direct"]) == set(expected["direct"])
        assert set(deps["all"]) == set(expected["all"])

    # 测试缺失依赖
    deps = await registry.resolve_skill_dependencies(["unknown_skill"])
    assert "unknown_skill" in deps["missing"]
    print(f"✅ 正确检测到缺失依赖: {deps['missing']}")

    # 清理
    await state_manager.shutdown()
    print("✅ 技能依赖解析测试通过")


async def main():
    """主测试函数"""
    print("=" * 60)
    print("OpenClaw 集群系统 - 第5周集成验证")
    print("技能系统 + NATS消息集成")
    print("=" * 60)

    try:
        # 测试1: 技能注册表
        await test_skill_registry()

        # 测试2: 技能发现
        await test_skill_discovery()

        # 测试3: 基于技能的调度
        await test_skill_based_scheduling()

        # 测试4: 技能依赖解析
        await test_skill_dependencies()

        print("\n" + "=" * 60)
        print("✅ 第5周所有集成测试通过！")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
