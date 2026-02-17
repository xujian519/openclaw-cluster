"""
OpenClaw 集群系统 - 技能发现服务

自动发现和注册节点上的技能
"""
import asyncio
import os
import json
from typing import Dict, List, Optional, Set
from pathlib import Path
from datetime import datetime

from common.logging import get_logger
from skills.skill_registry import SkillRegistry, SkillMetadata, SkillCategory

logger = get_logger(__name__)


class SkillDiscovery:
    """
    技能发现服务

    自动发现节点上的技能并注册到技能注册表
    """

    def __init__(
        self,
        skill_registry: SkillRegistry,
        skills_dir: str = "./skills",
        discovery_interval: int = 60,
    ):
        """
        初始化技能发现服务

        Args:
            skill_registry: 技能注册表
            skills_dir: 技能目录路径
            discovery_interval: 发现间隔（秒）
        """
        self.skill_registry = skill_registry
        self.skills_dir = Path(skills_dir)
        self.discovery_interval = discovery_interval

        # 发现状态
        self._is_running = False
        self._discovery_task: Optional[asyncio.Task] = None

        # 已发现的技能
        self._discovered_skills: Dict[str, SkillMetadata] = {}

        # 节点ID
        self._node_id: Optional[str] = None

    async def start(self, node_id: str):
        """
        启动技能发现服务

        Args:
            node_id: 当前节点ID
        """
        if self._is_running:
            logger.warning("技能发现服务已在运行")
            return

        self._node_id = node_id
        self._is_running = True

        # 立即执行一次发现
        await self._discover_skills()

        # 启动定期发现任务
        self._discovery_task = asyncio.create_task(self._discovery_loop())

        logger.info(
            f"技能发现服务已启动 "
            f"(节点: {node_id}, 目录: {self.skills_dir}, "
            f"间隔: {self.discovery_interval}秒)"
        )

    async def stop(self):
        """停止技能发现服务"""
        if not self._is_running:
            return

        self._is_running = False

        if self._discovery_task:
            self._discovery_task.cancel()
            try:
                await self._discovery_task
            except asyncio.CancelledError:
                pass

        logger.info("技能发现服务已停止")

    async def _discovery_loop(self):
        """发现循环"""
        while self._is_running:
            try:
                await asyncio.sleep(self.discovery_interval)
                await self._discover_skills()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"技能发现出错: {e}", exc_info=True)

    async def _discover_skills(self):
        """发现技能"""
        if not self.skills_dir.exists():
            logger.debug(f"技能目录不存在: {self.skills_dir}")
            return

        # 扫描技能目录
        discovered = set()

        # 遍历技能目录
        for skill_path in self.skills_dir.iterdir():
            if not skill_path.is_dir():
                continue

            skill_name = skill_path.name

            # 查找技能配置文件
            config_file = skill_path / "skill.json"
            if not config_file.exists():
                logger.debug(f"技能配置文件不存在: {skill_name}")
                continue

            try:
                # 读取技能配置
                with open(config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)

                # 创建技能元数据
                metadata = SkillMetadata(
                    name=config.get("name", skill_name),
                    description=config.get("description", ""),
                    category=SkillCategory(
                        config.get("category", SkillCategory.CUSTOM)
                    ),
                    version=config.get("version", "1.0.0"),
                    author=config.get("author", ""),
                    dependencies=config.get("dependencies", []),
                    required_resources=config.get("required_resources", {}),
                    tags=config.get("tags", []),
                )

                # 注册技能元数据
                await self.skill_registry.register_skill(metadata)

                # 注册技能实例
                if self._node_id:
                    await self.skill_registry.register_skill_instance(
                        metadata.name, self._node_id
                    )

                discovered.add(metadata.name)
                self._discovered_skills[metadata.name] = metadata

                logger.debug(f"发现技能: {metadata.name} v{metadata.version}")

            except Exception as e:
                logger.error(f"加载技能配置失败 {skill_name}: {e}")

        if discovered:
            logger.info(f"发现 {len(discovered)} 个技能: {', '.join(discovered)}")

    async def register_local_skills(
        self, skills: List[Dict[str, any]]
    ) -> int:
        """
        手动注册本地技能

        Args:
            skills: 技能配置列表

        Returns:
            成功注册的技能数量
        """
        registered = 0

        for skill_config in skills:
            try:
                metadata = SkillMetadata(
                    name=skill_config.get("name", ""),
                    description=skill_config.get("description", ""),
                    category=SkillCategory(
                        skill_config.get("category", SkillCategory.CUSTOM)
                    ),
                    version=skill_config.get("version", "1.0.0"),
                    author=skill_config.get("author", ""),
                    dependencies=skill_config.get("dependencies", []),
                    required_resources=skill_config.get("required_resources", {}),
                    tags=skill_config.get("tags", []),
                )

                # 注册技能元数据
                await self.skill_registry.register_skill(metadata)

                # 注册技能实例
                if self._node_id:
                    await self.skill_registry.register_skill_instance(
                        metadata.name, self._node_id
                    )

                registered += 1

            except Exception as e:
                logger.error(f"注册技能失败 {skill_config.get('name')}: {e}")

        if registered > 0:
            logger.info(f"手动注册了 {registered} 个技能")

        return registered

    async def get_discovered_skills(self) -> List[SkillMetadata]:
        """
        获取已发现的技能列表

        Returns:
            技能元数据列表
        """
        return list(self._discovered_skills.values())


class SkillManifestBuilder:
    """
    技能清单构建器

    用于生成技能的配置文件
    """

    @staticmethod
    def build_manifest(
        name: str,
        description: str,
        category: str = "custom",
        version: str = "1.0.0",
        author: str = "",
        dependencies: List[str] = None,
        required_resources: Dict[str, any] = None,
        tags: List[str] = None,
    ) -> Dict[str, any]:
        """
        构建技能清单

        Args:
            name: 技能名称
            description: 技能描述
            category: 技能类别
            version: 技能版本
            author: 作者
            dependencies: 依赖的其他技能
            required_resources: 所需资源
            tags: 标签

        Returns:
            技能配置字典
        """
        return {
            "name": name,
            "description": description,
            "category": category,
            "version": version,
            "author": author,
            "dependencies": dependencies or [],
            "required_resources": required_resources or {},
            "tags": tags or [],
        }

    @staticmethod
    async def save_manifest(
        skill_dir: str,
        manifest: Dict[str, any],
    ):
        """
        保存技能清单到文件

        Args:
            skill_dir: 技能目录
            manifest: 技能配置
        """
        skill_path = Path(skill_dir)
        skill_path.mkdir(parents=True, exist_ok=True)

        config_file = skill_path / "skill.json"

        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        logger.info(f"技能清单已保存: {config_file}")


# 预定义的常用技能配置
BUILTIN_SKILLS = [
    {
        "name": "python",
        "description": "Python代码执行和脚本运行",
        "category": "system",
        "version": "1.0.0",
        "author": "OpenClaw",
        "dependencies": [],
        "required_resources": {
            "cpu": "low",
            "memory": "medium",
        },
        "tags": ["programming", "scripting", "automation"],
    },
    {
        "name": "search",
        "description": "网络搜索和查询",
        "category": "network",
        "version": "1.0.0",
        "author": "OpenClaw",
        "dependencies": [],
        "required_resources": {
            "network": True,
        },
        "tags": ["web", "search", "query"],
    },
    {
        "name": "weather",
        "description": "天气信息查询",
        "category": "network",
        "version": "1.0.0",
        "author": "OpenClaw",
        "dependencies": ["search"],
        "required_resources": {
            "network": True,
        },
        "tags": ["weather", "forecast", "environment"],
    },
    {
        "name": "data-analysis",
        "description": "数据分析和处理",
        "category": "data_processing",
        "version": "1.0.0",
        "author": "OpenClaw",
        "dependencies": ["python"],
        "required_resources": {
            "cpu": "medium",
            "memory": "high",
        },
        "tags": ["data", "analysis", "statistics"],
    },
    {
        "name": "ml",
        "description": "机器学习模型训练和推理",
        "category": "machine_learning",
        "version": "1.0.0",
        "author": "OpenClaw",
        "dependencies": ["python", "data-analysis"],
        "required_resources": {
            "cpu": "high",
            "memory": "high",
            "gpu": "recommended",
        },
        "tags": ["ml", "ai", "training", "inference"],
    },
    {
        "name": "media",
        "description": "媒体文件处理（图像、视频、音频）",
        "category": "media_processing",
        "version": "1.0.0",
        "author": "OpenClaw",
        "dependencies": [],
        "required_resources": {
            "cpu": "high",
            "memory": "medium",
        },
        "tags": ["media", "image", "video", "audio"],
    },
]


async def register_builtin_skills(
    skill_discovery: SkillDiscovery,
    node_id: str,
) -> int:
    """
    注册内置技能

    Args:
        skill_discovery: 技能发现服务
        node_id: 节点ID

    Returns:
        注册的技能数量
    """
    return await skill_discovery.register_local_skills(BUILTIN_SKILLS)
