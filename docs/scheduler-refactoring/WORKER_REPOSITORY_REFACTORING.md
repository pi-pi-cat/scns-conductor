# Worker Repository 重构

## 📋 概述

本次重构将 `worker/executor.py` 和 `worker/process_utils.py` 中的数据库操作提取到独立的 Repository 层，与 Scheduler Repository 重构保持一致，实现统一的架构模式。

## 🎯 重构目标

1. **统一架构**：与 Scheduler Repository 保持相同的设计模式
2. **分离关注点**：将数据库操作从业务逻辑中分离
3. **提高可测试性**：Repository 可以独立测试
4. **代码复用**：数据库操作可以在其他地方复用

## 📦 新增文件

### `worker/repositories/worker_repository.py`

新增的 Repository 类，封装所有 Worker 相关的数据库操作。

#### 主要方法

##### 1. `get_job_by_id(session: Session, job_id: int) -> Optional[Job]`

根据 ID 获取作业，并从会话中分离（允许在会话外使用）。

**用途**：Worker 加载作业信息时使用。

##### 2. `update_job_completion(session: Session, job_id: int, exit_code: int) -> bool`

更新作业完成状态（COMPLETED 或 FAILED）。

**更新字段**：
- `state`: 根据退出码设置为 `COMPLETED` 或 `FAILED`
- `end_time`: 当前时间
- `exit_code`: 退出码
- `error_msg`: 如果退出码非 0，设置错误消息

##### 3. `update_job_failed(session: Session, job_id: int, error_msg: str, exit_code: str = "-1:0") -> bool`

标记作业失败。

**更新字段**：
- `state`: `FAILED`
- `end_time`: 当前时间
- `error_msg`: 错误消息
- `exit_code`: 退出码

##### 4. `get_unreleased_allocation(session: Session, job_id: int) -> Optional[ResourceAllocation]`

获取未释放的资源分配记录。

**用途**：查询作业的资源分配状态。

##### 5. `update_allocation_to_allocated(session: Session, job_id: int) -> Optional[ResourceAllocation]`

将资源分配状态从 `reserved` 更新为 `allocated`。

**用途**：Worker 真正开始执行作业时，将资源状态从预留更新为已分配。

##### 6. `create_allocation_as_allocated(...) -> ResourceAllocation`

创建资源分配记录（状态为 `allocated`）。

**用途**：异常情况处理，如果没有预留记录，直接创建 allocated 记录。

##### 7. `release_allocation(session: Session, job_id: int) -> Optional[Tuple[ResourceAllocation, ResourceStatus]]`

释放资源分配（更新状态为 `released`）。

**返回值**：`(资源分配对象, 旧状态)` 元组，用于判断是否需要更新 Redis 缓存。

##### 8. `update_process_id(session: Session, job_id: int, process_id: int) -> bool`

更新资源分配记录中的进程 ID。

**用途**：存储作业进程 ID 到数据库。

## 🔄 重构内容

### 修改前 (`worker/executor.py`)

```python
# 直接使用 SQLAlchemy 查询
job = session.query(Job).filter(Job.id == job_id).first()

# 直接更新作业状态
job.state = JobState.COMPLETED if exit_code == 0 else JobState.FAILED
job.end_time = datetime.utcnow()
job.exit_code = f"{exit_code}:0"

# 直接更新资源分配状态
allocation.status = ResourceStatus.ALLOCATED

# 直接释放资源
allocation.status = ResourceStatus.RELEASED
allocation.released_time = datetime.utcnow()
```

### 修改后 (`worker/executor.py`)

```python
# 使用 Repository 查询
job = WorkerRepository.get_job_by_id(session, job_id)

# 使用 Repository 更新作业状态
WorkerRepository.update_job_completion(session, job_id, exit_code)

# 使用 Repository 更新资源分配状态
WorkerRepository.update_allocation_to_allocated(session, job_id)

# 使用 Repository 释放资源
result = WorkerRepository.release_allocation(session, job_id)
if result:
    allocation, old_status = result
    # 根据旧状态决定是否更新缓存
```

### 修改前 (`worker/process_utils.py`)

```python
# 直接查询和更新
allocation = (
    session.query(ResourceAllocation)
    .filter(
        ResourceAllocation.job_id == job_id,
        ResourceAllocation.status != ResourceStatus.RELEASED,
    )
    .first()
)
if allocation:
    allocation.process_id = pid
```

### 修改后 (`worker/process_utils.py`)

```python
# 使用 Repository 更新
if WorkerRepository.update_process_id(session, job_id, pid):
    session.commit()
```

## 📊 代码变更统计

### 新增代码
- **文件**: `worker/repositories/worker_repository.py` (~280 行)
- **文件**: `worker/repositories/__init__.py`
- **方法**: 8 个静态方法

### 修改代码
- **文件**: `worker/executor.py`
  - 移除了直接的数据库查询代码
  - 移除了作业状态的直接更新
  - 移除了资源分配的直接操作
  - 添加了 `WorkerRepository` 的导入和使用

- **文件**: `worker/process_utils.py`
  - 移除了直接的数据库查询代码
  - 使用 `WorkerRepository.update_process_id()` 替代

## ✅ 重构优势

### 1. 架构统一
- 与 Scheduler Repository 保持相同的设计模式
- 统一的代码风格和结构
- 便于维护和理解

### 2. 关注点分离
- **业务逻辑**（`executor.py`）：专注于作业执行和流程控制
- **数据访问**（`worker_repository.py`）：专注于数据库操作

### 3. 可测试性提升
- Repository 方法可以独立进行单元测试
- 可以轻松 mock Repository 来测试执行器逻辑

### 4. 代码复用
- Repository 方法可以在其他模块中复用
- 统一的数据库操作接口

### 5. 维护性提升
- 数据库查询逻辑集中管理
- 修改查询逻辑时只需修改 Repository

## 🔍 设计模式

### Repository 模式

与 Scheduler Repository 保持一致的设计模式：

- **静态方法**：所有方法都是静态方法，便于调用
- **会话管理**：接受 `session` 参数，由调用者管理事务
- **单一职责**：专注于 Worker 相关的数据库操作

### 状态管理

Worker Repository 特别关注资源分配的状态转换：

1. **reserved → allocated**：Worker 开始执行时
2. **allocated → released**：作业完成时
3. **reserved → released**：异常情况（从未真正执行）

## 📝 使用示例

### 在 Worker 中使用

```python
from worker.repositories import WorkerRepository

class JobExecutor:
    def execute(self, job_id: int):
        with sync_db.get_session() as session:
            # 加载作业
            job = WorkerRepository.get_job_by_id(session, job_id)
            
            # 更新资源状态为 allocated
            WorkerRepository.update_allocation_to_allocated(session, job_id)
            session.commit()
            
            # 执行作业...
            
            # 释放资源
            result = WorkerRepository.release_allocation(session, job_id)
            if result:
                allocation, old_status = result
                if old_status == ResourceStatus.ALLOCATED:
                    # 更新缓存
                    self.resource_manager.release(allocation.allocated_cpus)
            
            # 更新作业状态
            WorkerRepository.update_job_completion(session, job_id, exit_code)
            session.commit()
```

## 🔗 与 Scheduler 的协作

### 资源状态流转

1. **Scheduler** 创建资源分配（`RESERVED`）
   ```python
   SchedulerRepository.create_resource_allocation(
       session, job_id, cpus, node_name, status=ResourceStatus.RESERVED
   )
   ```

2. **Worker** 开始执行时更新为 `ALLOCATED`
   ```python
   WorkerRepository.update_allocation_to_allocated(session, job_id)
   ```

3. **Worker** 完成时更新为 `RELEASED`
   ```python
   WorkerRepository.release_allocation(session, job_id)
   ```

### 数据一致性

- Scheduler 和 Worker 使用相同的 Repository 模式
- 统一的数据库操作接口
- 清晰的状态转换流程

## 🧪 测试建议

### Repository 测试

```python
def test_update_allocation_to_allocated():
    with sync_db.get_session() as session:
        # 创建测试数据（reserved 状态）
        allocation = ResourceAllocation(
            job_id=1,
            allocated_cpus=4,
            node_name="node1",
            status=ResourceStatus.RESERVED,
        )
        session.add(allocation)
        session.commit()
        
        # 测试更新
        result = WorkerRepository.update_allocation_to_allocated(session, 1)
        assert result is not None
        assert result.status == ResourceStatus.ALLOCATED
```

### Worker 测试（使用 Mock）

```python
from unittest.mock import Mock, patch

def test_execute_with_mock_repository():
    executor = JobExecutor()
    
    with patch('worker.executor.WorkerRepository') as mock_repo:
        mock_repo.get_job_by_id.return_value = MockJob()
        mock_repo.update_allocation_to_allocated.return_value = MockAllocation()
        
        executor.execute(1)
        
        mock_repo.get_job_by_id.assert_called_once()
        mock_repo.update_allocation_to_allocated.assert_called_once()
```

## 🔗 相关文档

- [Scheduler Repository 重构](./SCHEDULER_REPOSITORY_REFACTORING.md)
- [Cleanup Repository 设计](./cleanup-strategies/CLEANUP_REPOSITORY_DESIGN.md)
- [Scheduler 重构索引](./README.md)

## 📅 变更记录

- **2024-XX-XX**: 初始重构，提取 Worker 数据库操作到 Repository 层，与 Scheduler Repository 对齐

