# OpenClaw 集群系统 - 存储层文档

## 概述

存储层为OpenClaw集群系统提供完整的数据持久化和状态管理功能，采用SQLite作为底层存储，使用aiosqlite实现异步操作，确保高性能和并发安全。

## 架构设计

### 三层架构

```
┌─────────────────────────────────────────┐
│          StateManager (状态管理层)        │
│  - 内存缓存                               │
│  - 状态同步                               │
│  - 自动刷新                               │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│      Repository (数据访问层)              │
│  - TaskRepository                        │
│  - NodeRepository                        │
│  - 数据验证和转换                         │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│       Database (数据库层)                 │
│  - SQLite                                │
│  - 异步操作                               │
│  - 事务管理                               │
└─────────────────────────────────────────┘
```

### 核心组件

#### 1. Database (数据库层)
- **文件**: `storage/database.py`
- **功能**:
  - 异步数据库连接管理
  - 表结构初始化和迁移
  - 事务支持
  - 数据库备份和优化

#### 2. Repository (数据访问层)
- **文件**: `storage/repositories.py`
- **功能**:
  - TaskRepository: 任务CRUD操作
  - NodeRepository: 节点CRUD操作
  - 复杂查询支持
  - 数据验证和错误处理

#### 3. StateManager (状态管理层)
- **文件**: `storage/state_manager.py`
- **功能**:
  - 内存状态缓存
  - 自动持久化
  - 状态同步
  - 失联节点检测

## 数据模型

### Task (任务)
```python
@dataclass
class Task:
    # 基本信息
    task_id: str                  # 任务ID
    task_type: TaskType           # 任务类型
    name: str                     # 任务名称
    description: str              # 任务描述

    # 技能需求
    required_skills: List[str]    # 必需技能
    optional_skills: List[str]    # 可选技能

    # 调度信息
    status: TaskStatus            # 任务状态
    priority: TaskPriority        # 优先级
    assigned_node: str            # 分配的节点

    # 时间信息
    submitted_at: datetime        # 提交时间
    scheduled_at: datetime        # 调度时间
    started_at: datetime          # 开始时间
    completed_at: datetime        # 完成时间

    # 执行参数
    parameters: Dict[str, Any]    # 执行参数
    timeout: int                  # 超时时间
    retry_count: int              # 重试次数

    # 结果
    result: Any                   # 执行结果
    error: str                    # 错误信息
```

### NodeInfo (节点)
```python
@dataclass
class NodeInfo:
    # 基本信息
    node_id: str                  # 节点ID
    hostname: str                 # 主机名
    platform: str                 # 平台
    arch: str                     # 架构

    # 状态信息
    status: NodeStatus            # 节点状态
    cpu_usage: float              # CPU使用率
    memory_usage: float           # 内存使用率
    disk_usage: float             # 磁盘使用率

    # 能力信息
    available_skills: List[str]   # 可用技能
    max_concurrent_tasks: int     # 最大并发任务数
    running_tasks: int            # 当前运行任务数

    # 网络信息
    ip_address: str               # IP地址
    tailscale_ip: str             # Tailscale IP
    port: int                     # 服务端口

    # 性能指标
    total_tasks_processed: int    # 总处理任务数
    successful_tasks: int         # 成功任务数
    failed_tasks: int             # 失败任务数
```

## 使用指南

### 1. 初始化状态管理器

```python
from storage.database import Database
from storage.state_manager import StateManager

# 创建数据库实例
db = Database("./data/cluster.db")

# 创建状态管理器
state_manager = StateManager(db, auto_sync_interval=30)

# 初始化
await state_manager.initialize()
```

### 2. 管理节点

```python
from common.models import NodeInfo, NodeStatus
from datetime import datetime

# 创建节点
node = NodeInfo(
    node_id="worker_001",
    hostname="worker-host-1",
    platform="linux",
    arch="x64",
    status=NodeStatus.ONLINE,
    available_skills=["python", "data_processing"],
    max_concurrent_tasks=5,
    registered_at=datetime.now(),
    last_heartbeat=datetime.now(),
)

# 添加节点
await state_manager.add_node(node)

# 获取节点
node = await state_manager.get_node("worker_001")

# 更新节点状态
await state_manager.update_node_status("worker_001", NodeStatus.BUSY)

# 获取在线节点
online_nodes = await state_manager.get_online_nodes()

# 获取可用节点
available_nodes = await state_manager.get_available_nodes()
```

### 3. 管理任务

```python
from common.models import Task, TaskType, TaskStatus, TaskPriority

# 创建任务
task = Task.create(
    task_type=TaskType.BATCH,
    name="data_processing",
    description="处理大数据集",
    required_skills=["python", "data_processing"],
    priority=TaskPriority.HIGH,
    user_id="user_001",
)

# 添加任务
await state_manager.add_task(task)

# 分配任务到节点
task.assigned_node = "worker_001"
task.status = TaskStatus.SCHEDULED
await state_manager.update_task(task)

# 获取待处理任务
pending_tasks = await state_manager.get_pending_tasks()

# 更新任务状态
task.status = TaskStatus.RUNNING
await state_manager.update_task(task)
```

### 4. 查询集群状态

```python
# 获取完整状态
state = await state_manager.get_state()

print(f"总节点数: {state.total_nodes}")
print(f"在线节点数: {state.online_nodes}")
print(f"总任务数: {state.total_tasks}")
print(f"运行中任务数: {state.running_tasks}")

# 获取特定任务
task = await state_manager.get_task("task_id")

# 获取特定节点
node = await state_manager.get_node("node_id")
```

### 5. 检查失联节点

```python
# 检查超时的节点（120秒未发送心跳）
stale_nodes = await state_manager.check_stale_nodes(timeout_seconds=120)

for node_id in stale_nodes:
    print(f"节点 {node_id} 可能已失联")
```

### 6. 关闭状态管理器

```python
# 会自动同步状态并关闭数据库连接
await state_manager.shutdown()
```

## 性能特性

### 1. 异步操作
- 所有数据库操作都是异步的
- 使用aiosqlite实现非阻塞IO
- 支持高并发访问

### 2. 内存缓存
- 状态管理器维护内存缓存
- 减少数据库访问次数
- 提升查询性能

### 3. 自动同步
- 可配置的自动同步间隔
- 确保数据持久化
- 支持手动触发同步

### 4. 连接池
- 数据库连接复用
- 减少连接开销
- 提升并发性能

### 5. WAL模式
- 使用SQLite的WAL（Write-Ahead Logging）模式
- 提升并发读写性能
- 支持多个读者和一个写者同时操作

## 测试

运行测试：

```bash
# 运行所有存储层测试
pytest tests/test_storage.py -v

# 运行特定测试类
pytest tests/test_storage.py::TestTaskRepository -v

# 运行特定测试方法
pytest tests/test_storage.py::TestTaskRepository::test_create_task -v
```

测试覆盖：
- 数据库操作测试
- 任务仓库测试
- 节点仓库测试
- 状态管理器测试
- 集成测试

## 示例程序

运行演示程序：

```bash
python examples/storage_demo.py
```

演示程序展示：
- 初始化状态管理器
- 创建工作节点
- 创建任务
- 查询集群状态
- 模拟任务调度
- 模拟任务执行
- 检查失联节点
- 获取数据库统计

## 错误处理

所有存储层操作都包含完善的错误处理：

```python
try:
    await state_manager.add_task(task)
except Exception as e:
    logger.error(f"添加任务失败: {e}")
    # 处理错误
```

## 最佳实践

1. **使用状态管理器**: 优先使用StateManager而不是直接使用Repository
2. **定期同步**: 配置合适的自动同步间隔
3. **检查失联节点**: 定期调用check_stale_nodes检测失联节点
4. **关闭连接**: 使用完毕后调用shutdown方法
5. **错误处理**: 始终处理可能的异常

## 数据库维护

### 备份
```python
await db.backup("/path/to/backup.db")
```

### 优化
```python
await db.vacuum()
```

### 清理旧任务
```python
from common.models import TaskStatus

task_repo = TaskRepository(db)
deleted_count = await task_repo.cleanup_old_tasks(days=30)
```

## 配置选项

### StateManager配置
```python
state_manager = StateManager(
    database=db,
    auto_sync_interval=30  # 自动同步间隔（秒）
)
```

### Database配置
```python
db = Database(
    db_path="./data/cluster.db"  # 数据库文件路径
)
```

## 性能指标

- 数据库操作延迟: < 10ms (本地)
- 状态查询: < 1ms (内存缓存)
- 并发支持: 100+ 操作/秒
- 数据库大小: ~1KB/任务

## 未来改进

- [ ] 支持PostgreSQL作为后端
- [ ] 添加数据分片功能
- [ ] 实现数据归档策略
- [ ] 支持分布式事务
- [ ] 添加数据加密功能
