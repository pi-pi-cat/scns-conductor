# Worker模块改进分析

> **分析时间**: 2025-11-07  
> **版本**: v1.0.0

---

## 🔍 发现的问题

### 1. ❌ SchedulerDaemon缺少上下文管理器支持

**当前代码** (`worker/main.py`):
```python
scheduler_daemon = SchedulerDaemon(check_interval=5)
scheduler_daemon.start()
try:
    worker.work()
finally:
    scheduler_daemon.stop()
    scheduler_daemon.join(timeout=10)
```

**问题**:
- 资源管理不够pythonic
- 容易忘记清理
- 没有使用`with`语句

---

### 2. ❌ ResourceTracker可以使用描述符

**当前代码**:
```python
class ResourceTracker:
    @property
    def available_cpus(self) -> int:
        with self._lock:
            return self._total_cpus - self._used_cpus
    
    @property
    def used_cpus(self) -> int:
        with self._lock:
            return self._used_cpus
```

**问题**:
- 重复的锁获取代码
- 可以用描述符简化

---

### 3. ❌ 缺少恢复策略的抽象

**当前代码**:
```python
class RecoveryManager:
    def recover_on_startup(self):
        # 硬编码的恢复逻辑
        ...
```

**问题**:
- 恢复逻辑硬编码
- 难以扩展不同的恢复策略
- 缺少策略模式

---

### 4. ❌ 信号处理可以更优雅

**当前代码**:
```python
def setup_signal_handlers(worker, scheduler_daemon):
    def signal_handler(signum, frame):
        ...
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
```

**问题**:
- 函数嵌套，不够清晰
- 难以测试
- 缺少面向对象设计

---

### 5. ❌ 缺少资源变化观察者

**问题**:
- ResourceTracker状态变化时没有通知机制
- 无法实时监控资源使用
- 缺少观察者模式

---

### 6. ❌ 重复的数据库查询代码

**当前代码**:
```python
# 在多处重复
allocation = session.query(ResourceAllocation).filter(
    ResourceAllocation.job_id == job_id,
    ResourceAllocation.released == False
).first()
```

---

## ✅ 改进方案

### 改进1: 上下文管理器支持

创建 `worker/daemon.py`:

```python
"""
守护进程基类和调度器守护进程
"""
import threading
import time
from abc import ABC, abstractmethod
from typing import Optional
from contextlib import contextmanager
from loguru import logger

from core.config import get_settings
from .scheduler import ResourceScheduler


class DaemonThread(threading.Thread, ABC):
    """
    守护线程基类
    
    提供标准的守护线程功能：
    - 启动/停止控制
    - 上下文管理器支持
    - 优雅的资源清理
    """
    
    def __init__(self, name: str, check_interval: float = 5.0):
        """
        初始化守护线程
        
        Args:
            name: 线程名称
            check_interval: 检查间隔（秒）
        """
        super().__init__(daemon=True, name=name)
        self.check_interval = check_interval
        self._stop_event = threading.Event()
        self._started = False
    
    def __enter__(self):
        """上下文管理器入口"""
        self.start()
        self._started = True
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        if self._started:
            self.stop()
            self.join(timeout=10)
        return False
    
    @abstractmethod
    def do_work(self) -> None:
        """
        执行实际工作（子类实现）
        
        此方法会在循环中被调用
        """
        pass
    
    def run(self) -> None:
        """主循环"""
        logger.info(f"{self.name} started")
        
        while not self._stop_event.is_set():
            try:
                self.do_work()
            except Exception as e:
                logger.error(f"{self.name} error: {e}", exc_info=True)
            
            # 等待下一次检查
            self._stop_event.wait(self.check_interval)
        
        logger.info(f"{self.name} stopped")
    
    def stop(self) -> None:
        """停止守护线程"""
        self._stop_event.set()
    
    @property
    def is_running(self) -> bool:
        """检查是否正在运行"""
        return not self._stop_event.is_set()


class SchedulerDaemon(DaemonThread):
    """
    调度器守护进程
    
    周期性检查待处理作业并进行调度
    
    使用示例:
        # 方式1：传统方式
        daemon = SchedulerDaemon()
        daemon.start()
        try:
            ...
        finally:
            daemon.stop()
            daemon.join()
        
        # 方式2：上下文管理器（推荐）✅
        with SchedulerDaemon() as daemon:
            ...  # 自动启动和清理
    """
    
    def __init__(self, check_interval: float = 5.0):
        super().__init__(name="SchedulerDaemon", check_interval=check_interval)
        self.scheduler = ResourceScheduler()
        self._last_stats_time = 0
    
    def do_work(self) -> None:
        """执行调度工作"""
        # 调度待处理作业
        scheduled_jobs = self.scheduler.schedule_pending_jobs()
        
        if scheduled_jobs:
            logger.info(f"Scheduled {len(scheduled_jobs)} jobs")
        
        # 定期记录资源统计（每分钟）
        current_time = int(time.time())
        if current_time - self._last_stats_time >= 60:
            self._log_resource_stats()
            self._last_stats_time = current_time
    
    def _log_resource_stats(self) -> None:
        """记录资源统计信息"""
        stats = self.scheduler.get_resource_stats()
        logger.info(
            f"📊 Resource stats: {stats['used_cpus']}/{stats['total_cpus']} CPUs "
            f"({stats['utilization']:.1f}% utilization)"
        )
```

**使用示例**（更pythonic）:

```python
# worker/main.py
from .daemon import SchedulerDaemon

def main():
    # ... 初始化 ...
    
    # 使用上下文管理器（自动清理）
    with SchedulerDaemon(check_interval=5) as scheduler_daemon:
        worker.work()
    # 自动停止和清理
```

---

### 改进2: 线程安全的描述符属性

创建 `worker/descriptors.py`:

```python
"""
Worker模块的描述符定义
"""
import threading
from typing import Any, Optional


class ThreadSafeProperty:
    """
    线程安全的属性描述符
    
    自动处理锁的获取和释放
    """
    
    def __init__(self, attr_name: str, lock_name: str = "_lock"):
        self.attr_name = attr_name
        self.lock_name = lock_name
    
    def __get__(self, instance, owner):
        if instance is None:
            return self
        
        lock = getattr(instance, self.lock_name)
        with lock:
            return getattr(instance, self.attr_name)
    
    def __set__(self, instance, value):
        lock = getattr(instance, self.lock_name)
        with lock:
            setattr(instance, self.attr_name, value)


class ComputedProperty:
    """
    计算属性描述符（线程安全）
    
    基于其他属性计算值，自动使用锁保护
    """
    
    def __init__(self, compute_func, lock_name: str = "_lock"):
        self.compute_func = compute_func
        self.lock_name = lock_name
    
    def __get__(self, instance, owner):
        if instance is None:
            return self
        
        lock = getattr(instance, self.lock_name)
        with lock:
            return self.compute_func(instance)
```

**重构ResourceTracker**:

```python
from .descriptors import ComputedProperty

class ResourceTracker:
    """线程安全的CPU资源跟踪器（优化版）"""
    
    def __init__(self):
        self._lock = threading.Lock()
        settings = get_settings()
        self._total_cpus = settings.TOTAL_CPUS
        self._used_cpus = 0
        self._load_current_usage()
    
    # 使用描述符简化属性访问
    available_cpus = ComputedProperty(
        lambda self: self._total_cpus - self._used_cpus
    )
    
    used_cpus = ComputedProperty(
        lambda self: self._used_cpus
    )
    
    @property
    def total_cpus(self) -> int:
        """总CPU数（不需要锁，只读）"""
        return self._total_cpus
    
    # ... 其他方法保持不变 ...
```

---

### 改进3: 策略模式 - 恢复策略抽象

创建 `worker/recovery_strategies.py`:

```python
"""
恢复策略定义
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List
from datetime import datetime
from loguru import logger

from core.models import Job
from core.enums import JobState


@dataclass
class RecoveryResult:
    """恢复操作结果"""
    recovered_jobs: List[int]
    skipped_jobs: List[int]
    total_jobs: int
    success_rate: float
    duration_seconds: float
    
    def __str__(self) -> str:
        return (
            f"Recovery: {len(self.recovered_jobs)}/{self.total_jobs} jobs recovered "
            f"({self.success_rate:.1f}% success) in {self.duration_seconds:.2f}s"
        )


class RecoveryStrategy(ABC):
    """恢复策略抽象基类"""
    
    @abstractmethod
    def should_recover(self, job: Job) -> bool:
        """
        判断是否应该恢复此作业
        
        Args:
            job: 作业对象
        
        Returns:
            True if should recover
        """
        pass
    
    @abstractmethod
    def recover_job(self, job: Job) -> bool:
        """
        恢复作业
        
        Args:
            job: 作业对象
        
        Returns:
            True if recovered successfully
        """
        pass


class OrphanJobRecoveryStrategy(RecoveryStrategy):
    """
    孤儿作业恢复策略
    
    检查进程是否存在，不存在则标记为失败
    """
    
    def should_recover(self, job: Job) -> bool:
        return job.state == JobState.RUNNING
    
    def recover_job(self, job: Job) -> bool:
        import os
        from core.database import sync_db
        from core.models import ResourceAllocation
        
        # 检查进程
        with sync_db.get_session() as session:
            allocation = session.query(ResourceAllocation).filter(
                ResourceAllocation.job_id == job.id
            ).first()
            
            if not allocation or not allocation.process_id:
                return False
            
            try:
                os.kill(allocation.process_id, 0)
                return False  # 进程存在，不需要恢复
            except OSError:
                # 进程不存在，标记为失败
                job.state = JobState.FAILED
                job.end_time = datetime.utcnow()
                job.error_msg = "Worker 异常退出导致作业中断"
                job.exit_code = "-999:0"
                
                allocation.released = True
                allocation.released_time = datetime.utcnow()
                
                session.commit()
                return True


class TimeoutJobRecoveryStrategy(RecoveryStrategy):
    """
    超时作业恢复策略
    
    处理运行时间过长的作业
    """
    
    def __init__(self, max_runtime_hours: int = 72):
        self.max_runtime_hours = max_runtime_hours
    
    def should_recover(self, job: Job) -> bool:
        if job.state != JobState.RUNNING or not job.start_time:
            return False
        
        from datetime import timedelta
        max_runtime = timedelta(hours=self.max_runtime_hours)
        current_runtime = datetime.utcnow() - job.start_time
        
        return current_runtime > max_runtime
    
    def recover_job(self, job: Job) -> bool:
        logger.warning(f"Job {job.id} exceeded max runtime, marking as failed")
        
        job.state = JobState.FAILED
        job.end_time = datetime.utcnow()
        job.error_msg = f"Job exceeded maximum runtime of {self.max_runtime_hours} hours"
        job.exit_code = "-998:0"
        
        return True


class CompositeRecoveryStrategy(RecoveryStrategy):
    """
    组合恢复策略
    
    按顺序应用多个策略
    """
    
    def __init__(self, strategies: List[RecoveryStrategy]):
        self.strategies = strategies
    
    def should_recover(self, job: Job) -> bool:
        return any(s.should_recover(job) for s in self.strategies)
    
    def recover_job(self, job: Job) -> bool:
        for strategy in self.strategies:
            if strategy.should_recover(job):
                if strategy.recover_job(job):
                    return True
        return False
```

**重构RecoveryManager**:

```python
from .recovery_strategies import (
    RecoveryStrategy,
    OrphanJobRecoveryStrategy,
    TimeoutJobRecoveryStrategy,
    CompositeRecoveryStrategy,
    RecoveryResult,
)

class RecoveryManager:
    """恢复管理器（策略模式版）"""
    
    def __init__(self, strategy: Optional[RecoveryStrategy] = None):
        self.settings = get_settings()
        # 默认使用组合策略
        self.strategy = strategy or CompositeRecoveryStrategy([
            OrphanJobRecoveryStrategy(),
            TimeoutJobRecoveryStrategy(max_runtime_hours=72),
        ])
    
    def recover_on_startup(self) -> RecoveryResult:
        """使用策略进行恢复"""
        import time
        start_time = time.time()
        
        logger.info("开始执行 Worker 启动恢复检查...")
        
        with sync_db.get_session() as session:
            running_jobs = session.query(Job).filter(
                Job.state == JobState.RUNNING
            ).all()
            
            recovered = []
            skipped = []
            
            for job in running_jobs:
                if self.strategy.should_recover(job):
                    if self.strategy.recover_job(job):
                        recovered.append(job.id)
                    else:
                        skipped.append(job.id)
                else:
                    skipped.append(job.id)
            
            duration = time.time() - start_time
            total = len(running_jobs)
            success_rate = (len(recovered) / total * 100) if total > 0 else 100
            
            result = RecoveryResult(
                recovered_jobs=recovered,
                skipped_jobs=skipped,
                total_jobs=total,
                success_rate=success_rate,
                duration_seconds=duration,
            )
            
            logger.info(str(result))
            return result
```

---

### 改进4: 信号处理器类

创建 `worker/signal_handler.py`:

```python
"""
信号处理器
"""
import signal
from typing import Callable, List, Optional
from loguru import logger


class SignalHandler:
    """
    优雅的信号处理器
    
    支持多个回调函数和链式调用
    
    使用示例:
        handler = SignalHandler()
        handler.on_shutdown(lambda: logger.info("Cleaning up..."))
        handler.on_shutdown(worker.stop)
        handler.on_shutdown(daemon.stop)
        handler.register()  # 注册信号处理
    """
    
    def __init__(self):
        self._shutdown_callbacks: List[Callable] = []
        self._original_handlers = {}
    
    def on_shutdown(self, callback: Callable) -> "SignalHandler":
        """
        添加关闭回调
        
        Args:
            callback: 关闭时调用的函数
        
        Returns:
            self (支持链式调用)
        """
        self._shutdown_callbacks.append(callback)
        return self
    
    def register(self, signals: Optional[List[int]] = None) -> None:
        """
        注册信号处理器
        
        Args:
            signals: 要处理的信号列表（默认：SIGTERM, SIGINT）
        """
        if signals is None:
            signals = [signal.SIGTERM, signal.SIGINT]
        
        def handler(signum, frame):
            sig_name = signal.Signals(signum).name
            logger.info(f"🛑 Received {sig_name}, initiating graceful shutdown...")
            
            # 执行所有关闭回调
            for callback in self._shutdown_callbacks:
                try:
                    callback()
                except Exception as e:
                    logger.error(f"Error in shutdown callback: {e}")
        
        # 保存原始处理器并注册新处理器
        for sig in signals:
            self._original_handlers[sig] = signal.signal(sig, handler)
            logger.debug(f"Registered handler for {signal.Signals(sig).name}")
    
    def restore(self) -> None:
        """恢复原始信号处理器"""
        for sig, original_handler in self._original_handlers.items():
            signal.signal(sig, original_handler)
        self._original_handlers.clear()
```

**使用示例**:

```python
# worker/main.py
from .signal_handler import SignalHandler

def main():
    # ...初始化...
    
    # 设置信号处理（链式调用）
    signal_handler = SignalHandler()
    signal_handler \
        .on_shutdown(lambda: logger.info("Shutting down...")) \
        .on_shutdown(scheduler_daemon.stop) \
        .on_shutdown(worker.request_stop) \
        .register()
    
    # ...运行...
```

---

### 改进5: 观察者模式 - 资源变化通知

创建 `worker/observers.py`:

```python
"""
观察者模式实现
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from loguru import logger


class ResourceObserver(ABC):
    """资源观察者接口"""
    
    @abstractmethod
    def on_resource_allocated(self, cpus: int, stats: Dict[str, Any]) -> None:
        """资源分配时调用"""
        pass
    
    @abstractmethod
    def on_resource_released(self, cpus: int, stats: Dict[str, Any]) -> None:
        """资源释放时调用"""
        pass


class LoggingObserver(ResourceObserver):
    """日志观察者"""
    
    def on_resource_allocated(self, cpus: int, stats: Dict[str, Any]) -> None:
        logger.info(
            f"📈 Resource allocated: {cpus} CPUs "
            f"(utilization: {stats['utilization']:.1f}%)"
        )
    
    def on_resource_released(self, cpus: int, stats: Dict[str, Any]) -> None:
        logger.info(
            f"📉 Resource released: {cpus} CPUs "
            f"(utilization: {stats['utilization']:.1f}%)"
        )


class MetricsObserver(ResourceObserver):
    """指标收集观察者"""
    
    def __init__(self):
        self.allocations_count = 0
        self.releases_count = 0
        self.total_allocated = 0
        self.total_released = 0
    
    def on_resource_allocated(self, cpus: int, stats: Dict[str, Any]) -> None:
        self.allocations_count += 1
        self.total_allocated += cpus
    
    def on_resource_released(self, cpus: int, stats: Dict[str, Any]) -> None:
        self.releases_count += 1
        self.total_released += cpus
    
    def get_metrics(self) -> Dict[str, Any]:
        return {
            "allocations_count": self.allocations_count,
            "releases_count": self.releases_count,
            "total_allocated": self.total_allocated,
            "total_released": self.total_released,
        }


class AlertObserver(ResourceObserver):
    """告警观察者"""
    
    def __init__(self, threshold: float = 90.0):
        self.threshold = threshold
    
    def on_resource_allocated(self, cpus: int, stats: Dict[str, Any]) -> None:
        if stats['utilization'] > self.threshold:
            logger.warning(
                f"⚠️ High resource utilization: {stats['utilization']:.1f}%"
            )
    
    def on_resource_released(self, cpus: int, stats: Dict[str, Any]) -> None:
        pass  # 释放时不需要告警


class Observable:
    """可观察对象基类"""
    
    def __init__(self):
        self._observers: List[ResourceObserver] = []
    
    def attach(self, observer: ResourceObserver) -> None:
        """添加观察者"""
        if observer not in self._observers:
            self._observers.append(observer)
    
    def detach(self, observer: ResourceObserver) -> None:
        """移除观察者"""
        if observer in self._observers:
            self._observers.remove(observer)
    
    def notify_allocated(self, cpus: int, stats: Dict[str, Any]) -> None:
        """通知所有观察者：资源已分配"""
        for observer in self._observers:
            observer.on_resource_allocated(cpus, stats)
    
    def notify_released(self, cpus: int, stats: Dict[str, Any]) -> None:
        """通知所有观察者：资源已释放"""
        for observer in self._observers:
            observer.on_resource_released(cpus, stats)
```

**集成到ResourceTracker**:

```python
from .observers import Observable, LoggingObserver, MetricsObserver, AlertObserver

class ResourceTracker(Observable):
    """线程安全的CPU资源跟踪器（观察者模式版）"""
    
    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        settings = get_settings()
        self._total_cpus = settings.TOTAL_CPUS
        self._used_cpus = 0
        self._load_current_usage()
        
        # 默认添加日志和告警观察者
        self.attach(LoggingObserver())
        self.attach(AlertObserver(threshold=90.0))
    
    def allocate(self, cpus: int) -> bool:
        """分配资源（带观察者通知）"""
        with self._lock:
            if self.can_allocate(cpus):
                self._used_cpus += cpus
                stats = self.get_stats()
                
                # 通知观察者
                self.notify_allocated(cpus, stats)
                return True
            return False
    
    def release(self, cpus: int) -> None:
        """释放资源（带观察者通知）"""
        with self._lock:
            self._used_cpus = max(0, self._used_cpus - cpus)
            stats = self.get_stats()
            
            # 通知观察者
            self.notify_released(cpus, stats)
```

---

## 📊 改进效果对比

### 代码质量

| 指标 | 改进前 | 改进后 | 提升 |
|------|--------|--------|------|
| **Pythonic度** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ↑ 67% |
| **可扩展性** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ↑ 67% |
| **可测试性** | ⭐⭐ | ⭐⭐⭐⭐⭐ | ↑ 150% |
| **可维护性** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ↑ 25% |

### 代码简洁度

| 场景 | 改进前 | 改进后 | 减少 |
|------|--------|--------|------|
| **启动守护进程** | 8行 | 3行 | ↓ 63% |
| **信号处理** | 15行 | 5行 | ↓ 67% |
| **资源监控** | 无 | 2行 | N/A |

---

## 🎯 实施优先级

| 优先级 | 改进项 | 收益 | 难度 | 建议 |
|--------|--------|------|------|------|
| ⭐⭐⭐⭐⭐ | 1. 上下文管理器 | 高 | 低 | 立即实施 |
| ⭐⭐⭐⭐⭐ | 2. 信号处理器类 | 高 | 低 | 立即实施 |
| ⭐⭐⭐⭐ | 3. 策略模式恢复 | 中 | 中 | 推荐实施 |
| ⭐⭐⭐⭐ | 4. 观察者模式 | 中 | 中 | 推荐实施 |
| ⭐⭐⭐ | 5. 描述符属性 | 中 | 中 | 可选实施 |

---

**文档版本**: v1.0.0  
**创建时间**: 2025-11-07

