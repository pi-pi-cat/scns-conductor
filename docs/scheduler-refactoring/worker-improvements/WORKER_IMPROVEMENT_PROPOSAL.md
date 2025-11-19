# Worker 模块改进方案

## 📋 概述

本文档分析当前 Worker 模块的设计，并提出系统性的改进方案，以提高代码质量、可维护性、可测试性和系统健壮性。

## 🔍 当前架构分析

### 优点
1. ✅ 已使用 Repository 模式封装数据库操作
2. ✅ 使用 ResourceManager 统一管理资源
3. ✅ 基本的错误处理机制
4. ✅ 进程管理和超时处理

### 存在的问题

#### 1. 职责过重
- `JobExecutor` 承担了太多职责：作业加载、环境准备、进程管理、资源管理、状态更新
- 违反单一职责原则，难以测试和维护

#### 2. 错误处理不完善
- 缺少重试机制
- 错误信息不够详细
- 缺少错误分类和处理策略
- 没有作业取消机制

#### 3. 资源管理风险
- 资源分配和释放逻辑分散
- 缺少资源泄漏的防护机制
- 异常情况下资源可能无法正确释放

#### 4. 进程管理不足
- 缺少进程健康检查
- 无法监控进程资源使用情况
- 进程终止后的清理不完整

#### 5. 可观测性不足
- 缺少执行时间统计
- 缺少资源使用监控
- 缺少性能指标收集

#### 6. 测试性不足
- 依赖注入不完整
- 难以 mock 外部依赖
- 缺少单元测试支持

## 🎯 改进方案

### 方案 1: 引入执行上下文（Execution Context）

**问题**：当前执行流程中，作业信息、资源分配、进程信息等分散在各个方法中，缺少统一的上下文管理。

**解决方案**：引入 `JobExecutionContext` 类，统一管理作业执行过程中的所有状态。

```python
@dataclass
class JobExecutionContext:
    """作业执行上下文"""
    job: Job
    job_id: int
    allocation: Optional[ResourceAllocation]
    process: Optional[subprocess.Popen]
    process_id: Optional[int]
    start_time: datetime
    script_path: str
    stdout_path: Path
    stderr_path: Path
    env: dict
    error: Optional[Exception] = None
    exit_code: Optional[int] = None
    
    def is_running(self) -> bool:
        """检查作业是否正在运行"""
        return self.process is not None and self.process.poll() is None
    
    def elapsed_time(self) -> float:
        """获取已执行时间（秒）"""
        return (datetime.utcnow() - self.start_time).total_seconds()
```

**优势**：
- 统一管理执行状态
- 便于传递上下文信息
- 支持状态查询和监控

---

### 方案 2: 引入执行阶段（Execution Stages）

**问题**：当前执行流程是线性的，缺少阶段划分和钩子机制。

**解决方案**：将执行过程划分为明确的阶段，每个阶段提供钩子方法。

```python
class ExecutionStage(Enum):
    """执行阶段"""
    INITIALIZED = "initialized"      # 初始化
    LOADED = "loaded"                # 作业已加载
    RESOURCES_ALLOCATED = "resources_allocated"  # 资源已分配
    PREPARED = "prepared"            # 环境已准备
    RUNNING = "running"              # 正在执行
    COMPLETED = "completed"          # 执行完成
    FAILED = "failed"                # 执行失败
    CLEANED_UP = "cleaned_up"        # 已清理

class JobExecutor:
    def execute(self, job_id: int):
        context = JobExecutionContext(job_id=job_id)
        
        try:
            # 阶段 1: 初始化
            self._on_stage(ExecutionStage.INITIALIZED, context)
            context.job = self._load_job(job_id)
            self._on_stage(ExecutionStage.LOADED, context)
            
            # 阶段 2: 资源分配
            context.allocation = self._allocate_resources(context)
            self._on_stage(ExecutionStage.RESOURCES_ALLOCATED, context)
            
            # 阶段 3: 环境准备
            self._prepare_environment(context)
            self._on_stage(ExecutionStage.PREPARED, context)
            
            # 阶段 4: 执行
            context.exit_code = self._run_job(context)
            self._on_stage(ExecutionStage.COMPLETED, context)
            
        except Exception as e:
            context.error = e
            self._on_stage(ExecutionStage.FAILED, context)
        finally:
            self._cleanup(context)
            self._on_stage(ExecutionStage.CLEANED_UP, context)
    
    def _on_stage(self, stage: ExecutionStage, context: JobExecutionContext):
        """阶段钩子，可以被子类重写或通过观察者模式扩展"""
        logger.debug(f"Job {context.job_id} entered stage: {stage.value}")
```

**优势**：
- 清晰的执行流程
- 支持扩展和监控
- 便于添加中间件

---

### 方案 3: 引入执行器中间件（Middleware）

**问题**：缺少可扩展的执行前/后处理机制。

**解决方案**：使用中间件模式，支持执行前/后的处理。

```python
class ExecutionMiddleware:
    """执行中间件基类"""
    
    def before_execution(self, context: JobExecutionContext) -> JobExecutionContext:
        """执行前处理"""
        return context
    
    def after_execution(self, context: JobExecutionContext) -> JobExecutionContext:
        """执行后处理"""
        return context
    
    def on_error(self, context: JobExecutionContext, error: Exception):
        """错误处理"""
        pass

class MetricsMiddleware(ExecutionMiddleware):
    """指标收集中间件"""
    
    def before_execution(self, context: JobExecutionContext):
        context.start_time = datetime.utcnow()
        return context
    
    def after_execution(self, context: JobExecutionContext):
        duration = context.elapsed_time()
        # 记录指标
        logger.info(f"Job {context.job_id} executed in {duration:.2f}s")
        return context

class ResourceMonitoringMiddleware(ExecutionMiddleware):
    """资源监控中间件"""
    
    def before_execution(self, context: JobExecutionContext):
        # 记录资源使用前状态
        pass
    
    def after_execution(self, context: JobExecutionContext):
        # 记录资源使用后状态
        pass

class JobExecutor:
    def __init__(self, middlewares: List[ExecutionMiddleware] = None):
        self.middlewares = middlewares or [
            MetricsMiddleware(),
            ResourceMonitoringMiddleware(),
        ]
    
    def execute(self, job_id: int):
        context = JobExecutionContext(job_id=job_id)
        
        # 执行前中间件
        for middleware in self.middlewares:
            context = middleware.before_execution(context)
        
        try:
            # 执行作业
            self._do_execute(context)
        except Exception as e:
            context.error = e
            for middleware in self.middlewares:
                middleware.on_error(context, e)
        finally:
            # 执行后中间件
            for middleware in reversed(self.middlewares):
                context = middleware.after_execution(context)
```

**优势**：
- 高度可扩展
- 关注点分离
- 便于添加新功能（日志、监控、审计等）

---

### 方案 4: 改进错误处理和重试机制

**问题**：当前错误处理简单，缺少重试和错误分类。

**解决方案**：引入错误分类和重试策略。

```python
class ExecutionError(Exception):
    """执行错误基类"""
    pass

class JobNotFoundError(ExecutionError):
    """作业不存在"""
    pass

class ResourceAllocationError(ExecutionError):
    """资源分配错误"""
    pass

class ProcessExecutionError(ExecutionError):
    """进程执行错误"""
    pass

class RetryableError(ExecutionError):
    """可重试的错误"""
    pass

class JobExecutor:
    def execute(self, job_id: int, max_retries: int = 0):
        """执行作业，支持重试"""
        context = JobExecutionContext(job_id=job_id)
        retry_count = 0
        
        while retry_count <= max_retries:
            try:
                return self._do_execute(context)
            except RetryableError as e:
                retry_count += 1
                if retry_count <= max_retries:
                    logger.warning(
                        f"Job {job_id} failed (retryable), "
                        f"retrying {retry_count}/{max_retries}: {e}"
                    )
                    time.sleep(2 ** retry_count)  # 指数退避
                else:
                    raise
            except ExecutionError as e:
                # 不可重试的错误，直接抛出
                raise
```

**优势**：
- 提高系统健壮性
- 自动处理临时性错误
- 清晰的错误分类

---

### 方案 5: 引入作业取消机制

**问题**：当前无法取消正在运行的作业。

**解决方案**：添加取消机制和信号处理。

```python
class JobExecutor:
    def __init__(self):
        self._running_jobs: Dict[int, JobExecutionContext] = {}
        self._cancellation_events: Dict[int, threading.Event] = {}
    
    def execute(self, job_id: int):
        context = JobExecutionContext(job_id=job_id)
        cancellation_event = threading.Event()
        
        self._running_jobs[job_id] = context
        self._cancellation_events[job_id] = cancellation_event
        
        try:
            # 检查是否已取消
            if cancellation_event.is_set():
                raise JobCancelledError(f"Job {job_id} was cancelled before execution")
            
            # 执行作业
            self._do_execute(context, cancellation_event)
        finally:
            self._running_jobs.pop(job_id, None)
            self._cancellation_events.pop(job_id, None)
    
    def cancel_job(self, job_id: int) -> bool:
        """取消正在运行的作业"""
        if job_id in self._cancellation_events:
            self._cancellation_events[job_id].set()
            
            context = self._running_jobs.get(job_id)
            if context and context.process:
                # 终止进程
                kill_process_tree(context.process.pid)
                logger.info(f"Job {job_id} cancelled")
                return True
        return False
    
    def _do_execute(self, context: JobExecutionContext, cancellation_event: threading.Event):
        """执行作业，支持取消检查"""
        # 在关键点检查取消信号
        if cancellation_event.is_set():
            raise JobCancelledError(f"Job {context.job_id} was cancelled")
        
        # 执行作业...
        
        # 定期检查取消信号
        while context.process and context.process.poll() is None:
            if cancellation_event.wait(timeout=1):
                kill_process_tree(context.process.pid)
                raise JobCancelledError(f"Job {context.job_id} was cancelled during execution")
```

**优势**：
- 支持作业取消
- 优雅终止进程
- 资源及时释放

---

### 方案 6: 改进进程管理和监控

**问题**：进程管理不够完善，缺少健康检查。

**解决方案**：引入进程监控和健康检查。

```python
class ProcessMonitor:
    """进程监控器"""
    
    def __init__(self, check_interval: int = 5):
        self.check_interval = check_interval
        self._monitored_processes: Dict[int, JobExecutionContext] = {}
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
    
    def start_monitoring(self, job_id: int, context: JobExecutionContext):
        """开始监控进程"""
        self._monitored_processes[job_id] = context
        if not self._monitor_thread or not self._monitor_thread.is_alive():
            self._start_monitor_thread()
    
    def stop_monitoring(self, job_id: int):
        """停止监控进程"""
        self._monitored_processes.pop(job_id, None)
    
    def _start_monitor_thread(self):
        """启动监控线程"""
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="ProcessMonitor"
        )
        self._monitor_thread.start()
    
    def _monitor_loop(self):
        """监控循环"""
        while not self._stop_event.is_set():
            for job_id, context in list(self._monitored_processes.items()):
                if context.process:
                    # 检查进程是否存活
                    if context.process.poll() is not None:
                        # 进程已结束，但可能未正常退出
                        logger.warning(
                            f"Job {job_id} process ended unexpectedly "
                            f"(exit code: {context.process.returncode})"
                        )
                        self.stop_monitoring(job_id)
                    else:
                        # 检查资源使用
                        self._check_resource_usage(job_id, context)
            
            self._stop_event.wait(self.check_interval)
    
    def _check_resource_usage(self, job_id: int, context: JobExecutionContext):
        """检查资源使用情况"""
        try:
            import psutil
            process = psutil.Process(context.process.pid)
            
            # 检查内存使用
            memory_mb = process.memory_info().rss / 1024 / 1024
            if memory_mb > 10240:  # 超过 10GB
                logger.warning(
                    f"Job {job_id} using excessive memory: {memory_mb:.2f} MB"
                )
            
            # 检查 CPU 使用
            cpu_percent = process.cpu_percent(interval=1)
            logger.debug(f"Job {job_id} CPU usage: {cpu_percent:.1f}%")
            
        except Exception as e:
            logger.debug(f"Failed to check resource usage for job {job_id}: {e}")
```

**优势**：
- 实时监控进程状态
- 资源使用告警
- 异常检测

---

### 方案 7: 引入资源管理器（Resource Manager Wrapper）

**问题**：资源分配和释放逻辑分散，缺少统一管理。

**解决方案**：引入资源管理器包装器，确保资源正确释放。

```python
class ResourceManager:
    """资源管理器包装器，确保资源正确释放"""
    
    def __init__(self, resource_manager: ResourceManager):
        self.resource_manager = resource_manager
        self._allocated_resources: Dict[int, int] = {}  # job_id -> cpus
    
    @contextmanager
    def allocate_for_job(self, job_id: int, cpus: int):
        """为作业分配资源（上下文管理器）"""
        try:
            # 分配资源
            self._allocate(job_id, cpus)
            yield
        finally:
            # 确保释放资源
            self._release(job_id)
    
    def _allocate(self, job_id: int, cpus: int):
        """分配资源"""
        if job_id in self._allocated_resources:
            raise ResourceAllocationError(
                f"Job {job_id} already has allocated resources"
            )
        
        self.resource_manager.allocate(cpus)
        self._allocated_resources[job_id] = cpus
        logger.debug(f"Allocated {cpus} CPUs for job {job_id}")
    
    def _release(self, job_id: int):
        """释放资源"""
        if job_id in self._allocated_resources:
            cpus = self._allocated_resources.pop(job_id)
            self.resource_manager.release(cpus)
            logger.debug(f"Released {cpus} CPUs for job {job_id}")
        else:
            logger.warning(f"No allocated resources found for job {job_id}")

class JobExecutor:
    def __init__(self, resource_manager: ResourceManager = None):
        self.resource_manager = ResourceManager(
            resource_manager or ResourceManager()
        )
    
    def execute(self, job_id: int):
        context = JobExecutionContext(job_id=job_id)
        
        # 加载作业
        context.job = self._load_job(job_id)
        cpus = context.job.allocated_cpus
        
        # 使用上下文管理器确保资源释放
        with self.resource_manager.allocate_for_job(job_id, cpus):
            # 执行作业
            self._do_execute(context)
```

**优势**：
- 自动资源管理
- 防止资源泄漏
- 代码更简洁

---

### 方案 8: 改进测试性

**问题**：依赖注入不完整，难以测试。

**解决方案**：完善依赖注入，支持 mock。

```python
class JobExecutor:
    """作业执行器（改进版）"""
    
    def __init__(
        self,
        resource_manager: ResourceManager = None,
        worker_repository: WorkerRepository = None,
        process_monitor: ProcessMonitor = None,
        middlewares: List[ExecutionMiddleware] = None,
        settings: Settings = None,
    ):
        self.settings = settings or get_settings()
        self.resource_manager = resource_manager or ResourceManager()
        self.worker_repository = worker_repository or WorkerRepository()
        self.process_monitor = process_monitor or ProcessMonitor()
        self.middlewares = middlewares or []
    
    # ... 其他方法
```

**优势**：
- 便于单元测试
- 支持 mock 依赖
- 提高代码质量

---

## 📊 改进优先级

### 高优先级（立即实施）
1. ✅ **执行上下文（方案 1）** - 基础架构改进
2. ✅ **资源管理器包装器（方案 7）** - 防止资源泄漏
3. ✅ **改进错误处理（方案 4）** - 提高健壮性

### 中优先级（短期实施）
4. ✅ **执行阶段（方案 2）** - 提高可观测性
5. ✅ **作业取消机制（方案 5）** - 增强功能
6. ✅ **改进测试性（方案 8）** - 提高代码质量

### 低优先级（长期优化）
7. ✅ **执行器中间件（方案 3）** - 高级扩展
8. ✅ **进程监控（方案 6）** - 高级监控

---

## 🎯 实施建议

### 阶段 1: 基础改进（1-2 周）
- 引入执行上下文
- 改进资源管理
- 完善错误处理

### 阶段 2: 功能增强（2-3 周）
- 引入执行阶段
- 添加作业取消机制
- 改进测试性

### 阶段 3: 高级特性（3-4 周）
- 引入中间件机制
- 添加进程监控
- 性能优化

---

## 📝 总结

通过以上改进方案，Worker 模块将获得：

1. **更好的架构**：清晰的职责划分和模块化设计
2. **更高的健壮性**：完善的错误处理和资源管理
3. **更好的可观测性**：详细的执行阶段和监控
4. **更强的扩展性**：中间件机制支持功能扩展
5. **更好的测试性**：完善的依赖注入和 mock 支持

这些改进将显著提高 Worker 模块的质量、可维护性和可靠性。

