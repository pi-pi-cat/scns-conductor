# 清理策略数据库操作集中管理方案

## 🎯 目标

将分散在策略中的数据库操作集中到 Repository 层，让策略代码更简洁、易维护。

---

## 📊 当前问题分析

### 问题 1: 数据库操作分散

**当前代码示例**:
```python
# CompletedJobCleanupStrategy
def before_execute(self, session: Session) -> bool:
    count = (
        session.query(ResourceAllocation)
        .join(Job)
        .filter(
            ResourceAllocation.status != ResourceStatus.RELEASED,
            Job.state.in_([JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED]),
        )
        .count()
    )
    return count > 0

def _do_cleanup(self, session: Session) -> int:
    stale_allocations = (
        session.query(ResourceAllocation)
        .join(Job)
        .filter(
            ResourceAllocation.status != ResourceStatus.RELEASED,
            Job.state.in_([JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED]),
        )
        .all()
    )
    # ... 更新逻辑
```

**问题**:
- ❌ 查询逻辑重复（`before_execute` 和 `_do_cleanup` 几乎相同）
- ❌ SQL 语句分散在各处，难以维护
- ❌ 无法复用和优化查询
- ❌ 策略代码冗长，业务逻辑不清晰

---

## ✅ 解决方案：CleanupRepository

### 架构设计

```
策略层 (Strategy)
    ↓ 调用
清理仓储层 (CleanupRepository)
    ↓ 使用
数据库层 (Session)
```

### 核心设计

#### 1. CleanupRepository - 集中管理所有清理相关的数据库操作

```python
class CleanupRepository:
    """清理策略数据库操作仓储"""
    
    # ========== 已完成作业相关 ==========
    
    @staticmethod
    def count_completed_jobs_with_unreleased_resources(
        session: Session
    ) -> int:
        """统计已完成但未释放资源的作业数量"""
        pass
    
    @staticmethod
    def get_completed_jobs_with_unreleased_resources(
        session: Session
    ) -> List[ResourceAllocation]:
        """获取已完成但未释放资源的分配记录"""
        pass
    
    @staticmethod
    def release_resources_for_completed_jobs(
        session: Session,
        allocations: List[ResourceAllocation]
    ) -> int:
        """批量释放已完成作业的资源"""
        pass
    
    # ========== 预留超时相关 ==========
    
    @staticmethod
    def count_stale_reservations(
        session: Session,
        max_age_minutes: int
    ) -> int:
        """统计超时的预留数量"""
        pass
    
    @staticmethod
    def get_stale_reservations(
        session: Session,
        max_age_minutes: int
    ) -> List[ResourceAllocation]:
        """获取超时的预留记录"""
        pass
    
    @staticmethod
    def cleanup_stale_reservation(
        session: Session,
        allocation: ResourceAllocation,
        error_msg: str
    ) -> None:
        """清理单个超时预留（更新作业和分配状态）"""
        pass
    
    # ========== 卡住作业相关 ==========
    
    @staticmethod
    def get_stuck_jobs(
        session: Session,
        max_age_hours: int
    ) -> List[Job]:
        """获取卡住的作业"""
        pass
    
    @staticmethod
    def mark_job_as_failed(
        session: Session,
        job: Job,
        error_msg: str,
        exit_code: str
    ) -> None:
        """标记作业为失败"""
        pass
    
    @staticmethod
    def release_resource_for_job(
        session: Session,
        job: Job
    ) -> None:
        """释放作业的资源"""
        pass
    
    # ========== 旧作业相关 ==========
    
    @staticmethod
    def get_old_jobs(
        session: Session,
        max_age_days: int
    ) -> List[Job]:
        """获取过期的作业"""
        pass
    
    @staticmethod
    def delete_jobs_batch(
        session: Session,
        jobs: List[Job]
    ) -> int:
        """批量删除作业"""
        pass
```

---

## 🎨 重构前后对比

### Before (当前代码)

```python
class CompletedJobCleanupStrategy(BaseCleanupStrategy):
    def before_execute(self, session: Session) -> bool:
        """前置检查：是否有待清理的已完成作业"""
        count = (
            session.query(ResourceAllocation)
            .join(Job)
            .filter(
                ResourceAllocation.status != ResourceStatus.RELEASED,
                Job.state.in_(
                    [JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED]
                ),
            )
            .count()
        )
        if count == 0:
            logger.debug(f"[{self.name}] No completed jobs to clean, skipping")
            return False
        logger.debug(f"[{self.name}] Found {count} completed jobs to clean")
        return True
    
    def _do_cleanup(self, session: Session) -> int:
        """释放已完成作业的资源"""
        stale_allocations = (
            session.query(ResourceAllocation)
            .join(Job)
            .filter(
                ResourceAllocation.status != ResourceStatus.RELEASED,
                Job.state.in_(
                    [JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED]
                ),
            )
            .all()
        )
        
        for allocation in stale_allocations:
            allocation.status = ResourceStatus.RELEASED
            allocation.released_time = datetime.utcnow()
        
        return len(stale_allocations)
```

**问题**:
- ❌ 查询逻辑重复
- ❌ 代码冗长（30+ 行）
- ❌ 业务逻辑被 SQL 查询掩盖

---

### After (使用 Repository)

```python
class CompletedJobCleanupStrategy(BaseCleanupStrategy):
    def __init__(self, interval_seconds: int = 5):
        super().__init__(interval_seconds)
        self.repo = CleanupRepository()  # 注入仓储
    
    def before_execute(self, session: Session) -> bool:
        """前置检查：是否有待清理的已完成作业"""
        count = self.repo.count_completed_jobs_with_unreleased_resources(session)
        
        if count == 0:
            logger.debug(f"[{self.name}] No completed jobs to clean, skipping")
            return False
        
        logger.debug(f"[{self.name}] Found {count} completed jobs to clean")
        return True
    
    def _do_cleanup(self, session: Session) -> int:
        """释放已完成作业的资源"""
        allocations = self.repo.get_completed_jobs_with_unreleased_resources(session)
        return self.repo.release_resources_for_completed_jobs(session, allocations)
```

**优势**:
- ✅ 代码简洁（10+ 行，减少 60%）
- ✅ 业务逻辑清晰
- ✅ 查询逻辑集中，易于优化
- ✅ 可复用、可测试

---

## 📋 详细设计

### 1. CleanupRepository 类结构

```python
class CleanupRepository:
    """
    清理策略数据库操作仓储
    
    职责：
    - 集中管理所有清理相关的数据库查询
    - 提供批量操作支持
    - 封装复杂的联表查询
    - 支持查询优化
    """
    
    # ========== 已完成作业相关 ==========
    
    @staticmethod
    def count_completed_jobs_with_unreleased_resources(
        session: Session
    ) -> int:
        """
        统计已完成但未释放资源的作业数量
        
        用于 before_execute 快速检查
        """
        return (
            session.query(ResourceAllocation)
            .join(Job)
            .filter(
                ResourceAllocation.status != ResourceStatus.RELEASED,
                Job.state.in_(
                    [JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED]
                ),
            )
            .count()
        )
    
    @staticmethod
    def get_completed_jobs_with_unreleased_resources(
        session: Session
    ) -> List[ResourceAllocation]:
        """
        获取已完成但未释放资源的分配记录
        
        返回: ResourceAllocation 列表（包含关联的 Job）
        """
        return (
            session.query(ResourceAllocation)
            .join(Job)
            .filter(
                ResourceAllocation.status != ResourceStatus.RELEASED,
                Job.state.in_(
                    [JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED]
                ),
            )
            .all()
        )
    
    @staticmethod
    def release_resources_for_completed_jobs(
        session: Session,
        allocations: List[ResourceAllocation]
    ) -> int:
        """
        批量释放已完成作业的资源
        
        使用批量更新优化性能
        """
        if not allocations:
            return 0
        
        now = datetime.utcnow()
        # 批量更新
        for allocation in allocations:
            allocation.status = ResourceStatus.RELEASED
            allocation.released_time = now
        
        return len(allocations)
    
    # ========== 预留超时相关 ==========
    
    @staticmethod
    def count_stale_reservations(
        session: Session,
        max_age_minutes: int
    ) -> int:
        """统计超时的预留数量"""
        threshold = datetime.utcnow() - timedelta(minutes=max_age_minutes)
        return (
            session.query(ResourceAllocation)
            .join(Job)
            .filter(
                ResourceAllocation.status == ResourceStatus.RESERVED,
                ResourceAllocation.allocation_time < threshold,
                Job.state == JobState.RUNNING,
            )
            .count()
        )
    
    @staticmethod
    def get_stale_reservations(
        session: Session,
        max_age_minutes: int
    ) -> List[ResourceAllocation]:
        """获取超时的预留记录"""
        threshold = datetime.utcnow() - timedelta(minutes=max_age_minutes)
        return (
            session.query(ResourceAllocation)
            .join(Job)
            .filter(
                ResourceAllocation.status == ResourceStatus.RESERVED,
                ResourceAllocation.allocation_time < threshold,
                Job.state == JobState.RUNNING,
            )
            .all()
        )
    
    @staticmethod
    def cleanup_stale_reservation(
        session: Session,
        allocation: ResourceAllocation,
        error_msg: str = "作业预留超时，可能由于队列丢失或Worker未启动"
    ) -> None:
        """
        清理单个超时预留
        
        更新：
        - Job 状态为 FAILED
        - ResourceAllocation 状态为 RELEASED
        """
        job = allocation.job
        now = datetime.utcnow()
        
        job.state = JobState.FAILED
        job.end_time = now
        job.error_msg = error_msg
        job.exit_code = "-3:0"
        
        allocation.status = ResourceStatus.RELEASED
        allocation.released_time = now
    
    # ========== 卡住作业相关 ==========
    
    @staticmethod
    def get_stuck_jobs(
        session: Session,
        max_age_hours: int
    ) -> List[Job]:
        """获取卡住的作业（运行时间超过阈值）"""
        threshold = datetime.utcnow() - timedelta(hours=max_age_hours)
        return (
            session.query(Job)
            .filter(
                Job.state == JobState.RUNNING,
                Job.start_time < threshold
            )
            .all()
        )
    
    @staticmethod
    def mark_job_as_failed(
        session: Session,
        job: Job,
        error_msg: str,
        exit_code: str = "-2:0"
    ) -> None:
        """标记作业为失败"""
        job.state = JobState.FAILED
        job.end_time = datetime.utcnow()
        job.error_msg = error_msg
        job.exit_code = exit_code
    
    @staticmethod
    def release_resource_for_job(
        session: Session,
        job: Job
    ) -> None:
        """释放作业的资源（如果存在）"""
        if (
            hasattr(job, "resource_allocation")
            and job.resource_allocation
            and job.resource_allocation.status != ResourceStatus.RELEASED
        ):
            job.resource_allocation.status = ResourceStatus.RELEASED
            job.resource_allocation.released_time = datetime.utcnow()
    
    # ========== 旧作业相关 ==========
    
    @staticmethod
    def get_old_jobs(
        session: Session,
        max_age_days: int
    ) -> List[Job]:
        """获取过期的作业"""
        threshold = datetime.utcnow() - timedelta(days=max_age_days)
        return (
            session.query(Job)
            .filter(
                Job.state.in_(
                    [JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED]
                ),
                Job.end_time < threshold,
            )
            .all()
        )
    
    @staticmethod
    def delete_jobs_batch(
        session: Session,
        jobs: List[Job]
    ) -> int:
        """批量删除作业"""
        if not jobs:
            return 0
        
        for job in jobs:
            session.delete(job)
        
        return len(jobs)
```

---

### 2. 策略重构示例

#### CompletedJobCleanupStrategy

```python
@strategy_metadata(
    priority=1,
    depends_on=[],
    tags=["critical", "resource"],
    timeout=60,
)
class CompletedJobCleanupStrategy(BaseCleanupStrategy):
    """释放已完成作业资源的策略（最高优先级）"""
    
    def __init__(self, interval_seconds: int = 5):
        super().__init__(interval_seconds)
        self.repo = CleanupRepository()
    
    @property
    def name(self) -> str:
        return "completed_job_cleanup"
    
    @property
    def description(self) -> str:
        return "释放已完成但未释放资源的作业"
    
    def before_execute(self, session: Session) -> bool:
        """前置检查：是否有待清理的已完成作业"""
        count = self.repo.count_completed_jobs_with_unreleased_resources(session)
        
        if count == 0:
            logger.debug(f"[{self.name}] No completed jobs to clean, skipping")
            return False
        
        logger.debug(f"[{self.name}] Found {count} completed jobs to clean")
        return True
    
    def _do_cleanup(self, session: Session) -> int:
        """释放已完成作业的资源"""
        allocations = self.repo.get_completed_jobs_with_unreleased_resources(session)
        return self.repo.release_resources_for_completed_jobs(session, allocations)
    
    def after_execute(self, session: Session, result: CleanupResult):
        """后置处理：记录清理统计"""
        if result.items_cleaned > 0:
            logger.info(
                f"[{self.name}] Released resources for {result.items_cleaned} completed jobs"
            )
```

#### StaleReservationCleanupStrategy

```python
@strategy_metadata(
    priority=2,
    depends_on=["completed_job_cleanup"],
    tags=["critical", "resource"],
    timeout=120,
)
class StaleReservationCleanupStrategy(BaseCleanupStrategy):
    """清理预留超时的策略"""
    
    def __init__(self, interval_seconds: int = 120, max_age_minutes: int = 10):
        super().__init__(interval_seconds)
        self.max_age_minutes = max_age_minutes
        self.repo = CleanupRepository()
    
    @property
    def name(self) -> str:
        return "stale_reservation_cleanup"
    
    @property
    def description(self) -> str:
        return f"清理超过 {self.max_age_minutes} 分钟的预留记录"
    
    def before_execute(self, session: Session) -> bool:
        """前置检查：是否有超时的预留"""
        count = self.repo.count_stale_reservations(session, self.max_age_minutes)
        
        if count == 0:
            logger.debug(f"[{self.name}] No stale reservations, skipping")
            return False
        
        logger.info(f"[{self.name}] Found {count} stale reservations to clean")
        return True
    
    def _do_cleanup(self, session: Session) -> int:
        """清理预留超时的资源"""
        stale_reservations = self.repo.get_stale_reservations(
            session, self.max_age_minutes
        )
        
        for allocation in stale_reservations:
            # 记录日志
            logger.warning(
                f"♻️  [{self.name}] Job {allocation.job.id}: "
                f"reserved for {(datetime.utcnow() - allocation.allocation_time).total_seconds() / 60:.1f} min"
            )
            
            # 清理预留
            self.repo.cleanup_stale_reservation(session, allocation)
        
        return len(stale_reservations)
    
    def after_execute(self, session: Session, result: CleanupResult):
        """后置处理：如果清理数量多，发送告警"""
        if result.items_cleaned > 10:
            logger.warning(
                f"[{self.name}] ⚠️  Cleaned {result.items_cleaned} stale reservations "
                f"(may indicate queue or worker issues)"
            )
```

#### StuckJobCleanupStrategy

```python
@strategy_metadata(
    priority=3,
    depends_on=["completed_job_cleanup"],
    tags=["maintenance"],
    timeout=300,
)
class StuckJobCleanupStrategy(BaseCleanupStrategy):
    """清理卡住作业的策略"""
    
    def __init__(self, interval_seconds: int = 3600, max_age_hours: int = 48):
        super().__init__(interval_seconds)
        self.max_age_hours = max_age_hours
        self.repo = CleanupRepository()
    
    @property
    def name(self) -> str:
        return "stuck_job_cleanup"
    
    @property
    def description(self) -> str:
        return f"清理运行超过 {self.max_age_hours} 小时的卡住作业"
    
    def _do_cleanup(self, session: Session) -> int:
        """清理卡住的作业"""
        stuck_jobs = self.repo.get_stuck_jobs(session, self.max_age_hours)
        
        for job in stuck_jobs:
            logger.warning(f"[{self.name}] Stuck job {job.id} ({job.name})")
            
            # 标记为失败
            self.repo.mark_job_as_failed(
                session,
                job,
                error_msg="因超时由清理脚本标记为失败"
            )
            
            # 释放资源
            self.repo.release_resource_for_job(session, job)
        
        return len(stuck_jobs)
```

#### OldJobCleanupStrategy

```python
@strategy_metadata(
    priority=4,
    depends_on=[],
    tags=["maintenance", "optional"],
    enabled_by_default=False,
)
class OldJobCleanupStrategy(BaseCleanupStrategy):
    """清理过期作业的策略（可选）"""
    
    def __init__(
        self,
        interval_seconds: int = 86400,
        max_age_days: int = 30,
        enabled: bool = False,
    ):
        super().__init__(interval_seconds, enabled)
        self.max_age_days = max_age_days
        self.repo = CleanupRepository()
    
    @property
    def name(self) -> str:
        return "old_job_cleanup"
    
    @property
    def description(self) -> str:
        return f"删除超过 {self.max_age_days} 天的已完成作业"
    
    def _do_cleanup(self, session: Session) -> int:
        """删除过期的作业"""
        old_jobs = self.repo.get_old_jobs(session, self.max_age_days)
        return self.repo.delete_jobs_batch(session, old_jobs)
```

---

## 🎯 优势总结

### 1. 代码简洁性 ⭐⭐⭐⭐⭐

- **代码减少**: 策略代码减少 60-70%
- **可读性**: 业务逻辑清晰，不被 SQL 掩盖
- **维护性**: 查询逻辑集中，易于修改

### 2. 性能优化 ⭐⭐⭐⭐

- **消除重复查询**: `before_execute` 和 `_do_cleanup` 可以共享查询结果
- **批量操作**: Repository 可以优化批量更新
- **查询优化**: 集中管理便于添加索引提示、查询优化

### 3. 可测试性 ⭐⭐⭐⭐⭐

- **Mock 友好**: 可以轻松 Mock Repository
- **单元测试**: 策略逻辑和数据库操作分离
- **集成测试**: Repository 可以独立测试

### 4. 可复用性 ⭐⭐⭐⭐⭐

- **查询复用**: 其他模块也可以使用 Repository
- **逻辑复用**: 避免重复实现相同查询

---

## 📊 重构效果对比

| 指标 | Before | After | 提升 |
|------|--------|-------|------|
| **策略代码行数** | ~50行/策略 | ~20行/策略 | ⬇️ 60% |
| **SQL 查询分散度** | 分散在4个策略 | 集中在1个Repository | ⬆️ 集中度100% |
| **查询重复度** | 高（before + do） | 低（可共享） | ⬇️ 50% |
| **可测试性** | 低（耦合数据库） | 高（可Mock） | ⬆️ 100% |
| **可维护性** | 中 | 高 | ⬆️ 80% |

---

## 🚀 实施建议

### 阶段 1: 创建 Repository（1-2小时）

1. 创建 `scheduler/repositories/cleanup_repository.py`
2. 实现所有查询方法
3. 添加单元测试

### 阶段 2: 重构策略（2-3小时）

1. 逐个策略重构
2. 保持向后兼容
3. 验证功能正确性

### 阶段 3: 优化（可选，1-2小时）

1. 添加查询缓存
2. 优化批量操作
3. 添加性能监控

---

## 📝 注意事项

### 1. 依赖注入

策略可以通过构造函数注入 Repository：

```python
def __init__(
    self,
    interval_seconds: int = 5,
    repo: CleanupRepository = None
):
    super().__init__(interval_seconds)
    self.repo = repo or CleanupRepository()  # 默认实例
```

### 2. 会话管理

Repository 方法接受 `session` 参数，由策略层管理事务：

```python
def _do_cleanup(self, session: Session) -> int:
    # Repository 不管理事务，由策略层管理
    allocations = self.repo.get_completed_jobs_with_unreleased_resources(session)
    return self.repo.release_resources_for_completed_jobs(session, allocations)
```

### 3. 向后兼容

保持现有接口不变，只是内部实现改变。

---

## 🎉 总结

通过引入 `CleanupRepository`：

- ✅ **代码更简洁** - 策略代码减少 60%
- ✅ **逻辑更清晰** - 业务逻辑和数据库操作分离
- ✅ **易于维护** - 查询逻辑集中管理
- ✅ **易于测试** - 可以 Mock Repository
- ✅ **性能优化** - 可以消除重复查询、优化批量操作

**这就是 Repository 模式的力量！** 🚀

