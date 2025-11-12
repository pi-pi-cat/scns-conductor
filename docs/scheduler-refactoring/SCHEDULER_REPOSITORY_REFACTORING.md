# Scheduler Repository 重构

## 📋 概述

本次重构将 `scheduler/scheduler.py` 中的数据库操作提取到独立的 Repository 层，遵循单一职责原则和关注点分离，提高代码的可维护性和可测试性。

## 🎯 重构目标

1. **分离关注点**：将数据库操作从业务逻辑中分离
2. **提高可测试性**：Repository 可以独立测试
3. **代码复用**：数据库操作可以在其他地方复用
4. **统一风格**：与现有的 `CleanupRepository` 保持一致

## 📦 新增文件

### `scheduler/repositories/scheduler_repository.py`

新增的 Repository 类，封装所有调度器相关的数据库操作。

#### 主要方法

##### 1. `get_pending_jobs(session: Session) -> List[Job]`

获取所有 PENDING 状态的作业，按提交时间排序。

**用途**：调度器扫描待处理作业时使用。

**实现**：
```python
@staticmethod
def get_pending_jobs(session: Session) -> List[Job]:
    return (
        session.query(Job)
        .filter(Job.state == JobState.PENDING)
        .order_by(Job.submit_time)
        .all()
    )
```

##### 2. `create_resource_allocation(...) -> ResourceAllocation`

创建资源分配记录。

**参数**：
- `session`: 数据库会话
- `job_id`: 作业ID
- `allocated_cpus`: 分配的CPU数量
- `node_name`: 节点名称
- `status`: 资源状态（默认为 `RESERVED`）

**用途**：调度器分配资源时创建预留记录。

##### 3. `update_job_to_running(...) -> None`

更新作业状态为 RUNNING。

**参数**：
- `session`: 数据库会话
- `job`: 作业对象
- `node_name`: 节点名称

**更新字段**：
- `state`: `JobState.RUNNING`
- `start_time`: 当前时间
- `node_list`: 节点名称

**用途**：调度器将作业状态更新为运行中。

## 🔄 重构内容

### 修改前 (`scheduler/scheduler.py`)

```python
# 直接使用 SQLAlchemy 查询
pending_jobs = (
    session.query(Job)
    .filter(Job.state == JobState.PENDING)
    .order_by(Job.submit_time)
    .all()
)

# 直接创建 ResourceAllocation 对象
allocation = ResourceAllocation(
    job_id=job.id,
    allocated_cpus=cpus,
    node_name=self.settings.NODE_NAME,
    allocation_time=datetime.utcnow(),
    status=ResourceStatus.RESERVED,
)
session.add(allocation)

# 直接更新作业状态
job.state = JobState.RUNNING
job.start_time = datetime.utcnow()
job.node_list = self.settings.NODE_NAME
```

### 修改后 (`scheduler/scheduler.py`)

```python
# 使用 Repository 查询
pending_jobs = SchedulerRepository.get_pending_jobs(session)

# 使用 Repository 创建资源分配
SchedulerRepository.create_resource_allocation(
    session=session,
    job_id=job.id,
    allocated_cpus=cpus,
    node_name=self.settings.NODE_NAME,
    status=ResourceStatus.RESERVED,
)

# 使用 Repository 更新作业状态
SchedulerRepository.update_job_to_running(
    session=session,
    job=job,
    node_name=self.settings.NODE_NAME,
)
```

## 📊 代码变更统计

### 新增代码
- **文件**: `scheduler/repositories/scheduler_repository.py` (~100 行)
- **方法**: 3 个静态方法

### 修改代码
- **文件**: `scheduler/scheduler.py`
  - 移除了直接的数据库查询代码
  - 移除了 `ResourceAllocation` 的直接创建
  - 移除了作业状态的直接更新
  - 添加了 `SchedulerRepository` 的导入和使用

### 更新文件
- **文件**: `scheduler/repositories/__init__.py`
  - 添加了 `SchedulerRepository` 的导出

## ✅ 重构优势

### 1. 关注点分离
- **业务逻辑**（`scheduler.py`）：专注于调度算法和流程控制
- **数据访问**（`scheduler_repository.py`）：专注于数据库操作

### 2. 可测试性提升
- Repository 方法可以独立进行单元测试
- 可以轻松 mock Repository 来测试调度器逻辑

### 3. 代码复用
- Repository 方法可以在其他模块中复用
- 统一的数据库操作接口

### 4. 维护性提升
- 数据库查询逻辑集中管理
- 修改查询逻辑时只需修改 Repository

### 5. 一致性
- 与现有的 `CleanupRepository` 保持相同的设计模式
- 统一的代码风格和结构

## 🔍 设计模式

### Repository 模式

Repository 模式将数据访问逻辑封装在独立的类中，提供统一的接口来访问数据。

**优点**：
- 隐藏数据访问细节
- 提供抽象的数据访问接口
- 便于测试和维护

**实现特点**：
- 使用静态方法（与 `CleanupRepository` 保持一致）
- 接受 `session` 参数（由调用者管理事务）
- 专注于单一职责（调度相关的数据库操作）

## 📝 使用示例

### 在调度器中使用

```python
from scheduler.repositories import SchedulerRepository

class JobScheduler:
    def schedule(self) -> int:
        with sync_db.get_session() as session:
            # 查询待处理作业
            pending_jobs = SchedulerRepository.get_pending_jobs(session)
            
            for job in pending_jobs:
                # 创建资源分配
                SchedulerRepository.create_resource_allocation(
                    session=session,
                    job_id=job.id,
                    allocated_cpus=job.total_cpus_required,
                    node_name=self.settings.NODE_NAME,
                )
                
                # 更新作业状态
                SchedulerRepository.update_job_to_running(
                    session=session,
                    job=job,
                    node_name=self.settings.NODE_NAME,
                )
```

## 🧪 测试建议

### Repository 测试

```python
def test_get_pending_jobs():
    with sync_db.get_session() as session:
        # 创建测试数据
        job = Job(...)
        session.add(job)
        session.commit()
        
        # 测试查询
        jobs = SchedulerRepository.get_pending_jobs(session)
        assert len(jobs) == 1
        assert jobs[0].state == JobState.PENDING
```

### 调度器测试（使用 Mock）

```python
from unittest.mock import Mock, patch

def test_schedule_with_mock_repository():
    scheduler = JobScheduler()
    
    with patch('scheduler.scheduler.SchedulerRepository') as mock_repo:
        mock_repo.get_pending_jobs.return_value = [MockJob()]
        
        result = scheduler.schedule()
        
        mock_repo.get_pending_jobs.assert_called_once()
```

## 🔗 相关文档

- [Cleanup Repository 设计](../scheduler-refactoring/cleanup-strategies/CLEANUP_REPOSITORY_DESIGN.md)
- [Cleanup Repository 实现](../scheduler-refactoring/cleanup-strategies/CLEANUP_REPOSITORY_IMPLEMENTATION.md)
- [Scheduler 重构索引](../scheduler-refactoring/README.md)

## 📅 变更记录

- **2024-XX-XX**: 初始重构，提取数据库操作到 Repository 层

