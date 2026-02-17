"""
OpenClaw 集群系统 - 技能注册表

管理集群中所有技能的注册、发现和依赖解析
"""
import asyncio
from typing import Dict, List, Set, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from common.logging import get_logger
from storage.state_manager import StateManager

logger = get_logger(__name__)


class SkillCategory(Enum):
    """技能类别"""
    # 数据处理
    DATA_PROCESSING = "data_processing"
    # 机器学习
    MACHINE_LEARNING = "machine_learning"
    # 网络请求
    NETWORK = "network"
    # 文件操作
    FILE_OPERATION = "file_operation"
    # 媒体处理
    MEDIA_PROCESSING = "media_processing"
    # 文本处理
    TEXT_PROCESSING = "text_processing"
    # 系统操作
    SYSTEM = "system"
    # 自定义
    CUSTOM = "custom"


@dataclass
class SkillMetadata:
    """
    技能元数据

    描述技能的详细信息
    """
    # 技能名称
    name: str
    # 技能描述
    description: str
    # 技能类别
    category: SkillCategory
    # 技能版本
    version: str = "1.0.0"
    # 作者
    author: str = ""
    # 依赖的其他技能
    dependencies: List[str] = field(default_factory=list)
    # 所需资源
    required_resources: Dict[str, Any] = field(default_factory=dict)
    # 标签
    tags: List[str] = field(default_factory=list)
    # 创建时间
    created_at: datetime = field(default_factory=datetime.now)
    # 最后更新时间
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "version": self.version,
            "author": self.author,
            "dependencies": self.dependencies,
            "required_resources": self.required_resources,
            "tags": self.tags,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillMetadata":
        """从字典创建"""
        return cls(
            name=data["name"],
            description=data["description"],
            category=SkillCategory(data.get("category", SkillCategory.CUSTOM)),
            version=data.get("version", "1.0.0"),
            author=data.get("author", ""),
            dependencies=data.get("dependencies", []),
            required_resources=data.get("required_resources", {}),
            tags=data.get("tags", []),
        )


@dataclass
class SkillInstance:
    """
    技能实例

    记录技能在节点上的实例信息
    """
    # 技能名称
    skill_name: str
    # 节点ID
    node_id: str
    # 实例状态
    is_available: bool = True
    # 最后心跳时间
    last_heartbeat: datetime = field(default_factory=datetime.now)
    # 使用次数
    usage_count: int = 0
    # 成功率
    success_rate: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "skill_name": self.skill_name,
            "node_id": self.node_id,
            "is_available": self.is_available,
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "usage_count": self.usage_count,
            "success_rate": self.success_rate,
        }


class SkillRegistry:
    """
    技能注册表

    管理集群中所有技能的注册和查询
    """

    def __init__(self, state_manager: StateManager):
        """
        初始化技能注册表

        Args:
            state_manager: 状态管理器
        """
        self.state_manager = state_manager

        # 技能元数据注册表 (skill_name -> SkillMetadata)
        self._skills: Dict[str, SkillMetadata] = {}

        # 技能实例 (skill_name -> List[SkillInstance])
        self._skill_instances: Dict[str, List[SkillInstance]] = {}

        # 节点技能索引 (node_id -> Set[skill_name])
        self._node_skills: Dict[str, Set[str]] = {}

        # 锁
        self._lock = asyncio.Lock()

        # 统计信息
        self._stats = {
            "total_skills": 0,
            "total_instances": 0,
            "total_registrations": 0,
        }

    async def register_skill(self, metadata: SkillMetadata) -> bool:
        """
        注册技能

        Args:
            metadata: 技能元数据

        Returns:
            是否注册成功
        """
        async with self._lock:
            skill_name = metadata.name

            # 检查技能是否已注册
            if skill_name in self._skills:
                # 更新现有技能
                existing = self._skills[skill_name]
                existing.description = metadata.description
                existing.version = metadata.version
                existing.author = metadata.author
                existing.dependencies = metadata.dependencies
                existing.required_resources = metadata.required_resources
                existing.tags = metadata.tags
                existing.updated_at = datetime.now()

                logger.info(f"技能元数据已更新: {skill_name}")
            else:
                # 注册新技能
                self._skills[skill_name] = metadata
                self._stats["total_skills"] += 1
                self._stats["total_registrations"] += 1

                logger.info(
                    f"技能已注册: {skill_name} "
                    f"(类别: {metadata.category.value}, 版本: {metadata.version})"
                )

            return True

    async def register_skill_instance(
        self, skill_name: str, node_id: str
    ) -> bool:
        """
        注册技能实例

        Args:
            skill_name: 技能名称
            node_id: 节点ID

        Returns:
            是否注册成功
        """
        async with self._lock:
            # 检查技能是否已注册
            if skill_name not in self._skills:
                logger.warning(f"技能未注册，无法注册实例: {skill_name}")
                return False

            # 创建技能实例
            instance = SkillInstance(
                skill_name=skill_name,
                node_id=node_id,
            )

            # 添加到技能实例列表
            if skill_name not in self._skill_instances:
                self._skill_instances[skill_name] = []

            # 检查是否已有该节点的实例
            existing_instances = [
                inst for inst in self._skill_instances[skill_name]
                if inst.node_id == node_id
            ]

            if existing_instances:
                # 更新现有实例
                existing_instances[0].is_available = True
                existing_instances[0].last_heartbeat = datetime.now()
                logger.debug(f"技能实例已更新: {skill_name}@{node_id}")
            else:
                # 添加新实例
                self._skill_instances[skill_name].append(instance)
                self._stats["total_instances"] += 1

                logger.info(f"技能实例已注册: {skill_name}@{node_id}")

            # 更新节点技能索引
            if node_id not in self._node_skills:
                self._node_skills[node_id] = set()
            self._node_skills[node_id].add(skill_name)

            return True

    async def unregister_skill_instance(
        self, skill_name: str, node_id: str
    ) -> bool:
        """
        注销技能实例

        Args:
            skill_name: 技能名称
            node_id: 节点ID

        Returns:
            是否注销成功
        """
        async with self._lock:
            if skill_name not in self._skill_instances:
                return False

            # 查找并移除实例
            instances = self._skill_instances[skill_name]
            original_count = len(instances)

            instances[:] = [
                inst for inst in instances
                if not (inst.skill_name == skill_name and inst.node_id == node_id)
            ]

            if len(instances) < original_count:
                self._stats["total_instances"] -= 1

                # 更新节点技能索引
                if node_id in self._node_skills:
                    self._node_skills[node_id].discard(skill_name)

                logger.info(f"技能实例已注销: {skill_name}@{node_id}")
                return True

            return False

    async def get_skill_metadata(self, skill_name: str) -> Optional[SkillMetadata]:
        """
        获取技能元数据

        Args:
            skill_name: 技能名称

        Returns:
            技能元数据，如果不存在则返回None
        """
        async with self._lock:
            return self._skills.get(skill_name)

    async def get_skill_instances(
        self, skill_name: str
    ) -> List[SkillInstance]:
        """
        获取技能的所有实例

        Args:
            skill_name: 技能名称

        Returns:
            技能实例列表
        """
        async with self._lock:
            return list(self._skill_instances.get(skill_name, []))

    async def get_available_nodes_for_skill(
        self, skill_name: str
    ) -> List[str]:
        """
        获取具备指定技能的可用节点

        Args:
            skill_name: 技能名称

        Returns:
            节点ID列表
        """
        async with self._lock:
            instances = self._skill_instances.get(skill_name, [])
            return [
                inst.node_id
                for inst in instances
                if inst.is_available
            ]

    async def get_node_skills(self, node_id: str) -> Set[str]:
        """
        获取节点具备的所有技能

        Args:
            node_id: 节点ID

        Returns:
            技能名称集合
        """
        async with self._lock:
            return set(self._node_skills.get(node_id, set()))

    async def list_skills(
        self, category: Optional[SkillCategory] = None
    ) -> List[SkillMetadata]:
        """
        列出所有技能

        Args:
            category: 可选的技能类别过滤

        Returns:
            技能元数据列表
        """
        async with self._lock:
            skills = list(self._skills.values())

            if category:
                skills = [s for s in skills if s.category == category]

            return skills

    async def resolve_skill_dependencies(
        self, skill_names: List[str]
    ) -> Dict[str, List[str]]:
        """
        解析技能依赖关系

        Args:
            skill_names: 需要解析的技能列表

        Returns:
            依赖关系字典 {
                "direct": 直接依赖列表,
                "all": 所有依赖列表（包括传递依赖）,
                "missing": 缺失的依赖列表
            }
        """
        async with self._lock:
            direct = set()
            all_deps = set()
            missing = set()

            def resolve_deps(name: str, visited: Set[str] = None):
                """递归解析依赖"""
                if visited is None:
                    visited = set()

                if name in visited:
                    return

                visited.add(name)

                skill = self._skills.get(name)
                if not skill:
                    missing.add(name)
                    return

                for dep in skill.dependencies:
                    direct.add(dep)
                    all_deps.add(dep)
                    resolve_deps(dep, visited)

            # 解析所有技能的依赖
            for skill_name in skill_names:
                skill = self._skills.get(skill_name)
                if not skill:
                    # 主技能缺失
                    missing.add(skill_name)
                    continue

                for dep in skill.dependencies:
                    direct.add(dep)
                    all_deps.add(dep)
                    resolve_deps(dep)

            return {
                "direct": list(direct),
                "all": list(all_deps),
                "missing": list(missing),
            }

    async def find_skills_by_tags(self, tags: List[str]) -> List[SkillMetadata]:
        """
        按标签查找技能

        Args:
            tags: 标签列表

        Returns:
            匹配的技能列表
        """
        async with self._lock:
            tag_set = set(tags)
            return [
                skill
                for skill in self._skills.values()
                if tag_set & set(skill.tags)
            ]

    async def update_skill_usage(
        self, skill_name: str, node_id: str, success: bool = True
    ):
        """
        更新技能使用统计

        Args:
            skill_name: 技能名称
            node_id: 节点ID
            success: 是否成功
        """
        async with self._lock:
            if skill_name not in self._skill_instances:
                return

            for instance in self._skill_instances[skill_name]:
                if instance.node_id == node_id:
                    instance.usage_count += 1

                    # 更新成功率 (使用移动平均)
                    alpha = 0.1  # 平滑因子
                    instance.success_rate = (
                        alpha * (1.0 if success else 0.0) +
                        (1 - alpha) * instance.success_rate
                    )

                    break

    async def cleanup_stale_instances(self, timeout_seconds: int = 300) -> int:
        """
        清理失活的技能实例

        Args:
            timeout_seconds: 超时秒数

        Returns:
            清理的实例数量
        """
        async with self._lock:
            from datetime import timedelta

            now = datetime.now()
            timeout = timedelta(seconds=timeout_seconds)
            cleaned = 0

            for skill_name, instances in list(self._skill_instances.items()):
                # 过滤出过期实例
                active_instances = [
                    inst for inst in instances
                    if (now - inst.last_heartbeat) <= timeout or not inst.is_available
                ]

                stale_count = len(instances) - len(active_instances)
                cleaned += stale_count

                if stale_count > 0:
                    self._skill_instances[skill_name] = active_instances
                    logger.info(
                        f"清理了 {stale_count} 个过期实例: {skill_name}"
                    )

            self._stats["total_instances"] -= cleaned

            return cleaned

    async def get_stats(self) -> Dict[str, Any]:
        """
        获取注册表统计信息

        Returns:
            统计信息字典
        """
        async with self._lock:
            # 按类别统计
            category_counts = {}
            for skill in self._skills.values():
                category = skill.category.value
                category_counts[category] = category_counts.get(category, 0) + 1

            return {
                **self._stats,
                "category_counts": category_counts,
                "nodes_with_skills": len(self._node_skills),
            }
