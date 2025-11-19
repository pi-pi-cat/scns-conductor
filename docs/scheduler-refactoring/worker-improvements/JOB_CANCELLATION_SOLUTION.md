# 作业取消方案 - 优雅的进程终止机制

## 📋 问题分析

### 当前问题

1. **只修改数据库，不终止进程**
   - 取消操作只更新数据库状态
   - 实际进程仍在运行，占用资源
   - 资源泄漏风险

2. **进程终止不完整**
   - 只发送 SIGTERM，没有等待和 SIGKILL 的完整流程
   - 没有进程状态检查
   - 没有重试机制

3. **跨进程通信问题**
   - API 进程和 Worker 进程分离
   - 无法直接通知 Worker 进行优雅处理
   - 只能通过 PID 强制 kill

4. **缺少取消信号机制**
   - Worker 无法感知取消请求
   - 无法在关键点检查取消状态
   - 无法优雅清理资源

### 根本原因

```
API 进程                    Worker 进程
    │                            │
    │  cancel_job(job_id)        │
    │      ↓                     │
    │  查询数据库                │
    │      ↓                     │
    │  kill(pid) ────────────────┼──> 进程被强制终止
    │      ↓                     │
    │  更新数据库                │
    │                            │
    │  ❌ 无法通知 Worker        │
    │  ❌ 无法优雅处理           │
    │  ❌ 无法清理资源           │
```

---

## 🎯 解决方案设计

### 方案架构

```
┌─────────────────────────────────────────────────────────────┐
│                     取消请求流程                              │
└─────────────────────────────────────────────────────────────┘

API 进程                          Worker 进程
    │                                 │
    │  1. 设置取消标志                │
    │     (Redis/数据库)              │
    │         │                       │
    │         │                       │  2. 定期检查取消标志
    │         │                       │     (轮询/订阅)
    │         │                       │         │
    │         │                       │         │ 检测到取消
    │         │                       │         │
    │  3. 发送终止信号                │  4. 优雅终止进程
    │     (SIGTERM)                   │     (清理资源)
    │         │                       │         │
    │         │                       │         │
    │  5. 等待进程结束                │  5. 进程结束
    │     (超时检查)                  │
    │         │                       │
    │  6. 强制终止 (SIGKILL)          │
    │     (如果超时)                  │
    │         │                       │
    │  7. 更新数据库状态              │
    │  8. 释放资源                    │
```

---

## ✅ 推荐方案：信号机制 + 优雅终止

### 方案 1: Redis 信号机制（推荐）⭐

**原理**：使用 Redis 作为取消信号的中介，Worker 定期检查取消标志。

#### 架构设计

```
取消请求 → Redis 信号 → Worker 检查 → 优雅终止
```

#### 实现步骤

##### 1. 创建取消信号管理器

```python
# worker/cancellation.py
"""
作业取消信号管理器

使用 Redis 作为取消信号的中介，支持跨进程通信
"""

import time
from typing import Optional
from loguru import logger

from core.redis_client import redis_manager
from core.config import get_settings


class CancellationManager:
    """取消信号管理器"""
    
    def __init__(self):
        self.settings = get_settings()
        self.redis = redis_manager.get_connection()
        self._signal_key_prefix = "job:cancel:"
    
    def request_cancellation(self, job_id: int) -> bool:
        """
        请求取消作业
        
        Args:
            job_id: 作业ID
            
        Returns:
            是否成功设置取消标志
        """
        try:
            key = f"{self._signal_key_prefix}{job_id}"
            # 设置取消标志，TTL 为 1 小时（防止信号泄漏）
            self.redis.setex(key, 3600, "1")
            logger.info(f"✅ Cancellation signal set for job {job_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to set cancellation signal for job {job_id}: {e}")
            return False
    
    def is_cancelled(self, job_id: int) -> bool:
        """
        检查作业是否被请求取消
        
        Args:
            job_id: 作业ID
            
        Returns:
            是否被取消
        """
        try:
            key = f"{self._signal_key_prefix}{job_id}"
            return self.redis.exists(key) > 0
        except Exception as e:
            logger.error(f"Failed to check cancellation signal for job {job_id}: {e}")
            return False
    
    def clear_cancellation(self, job_id: int) -> bool:
        """
        清除取消标志（作业完成后）
        
        Args:
            job_id: 作业ID
            
        Returns:
            是否成功清除
        """
        try:
            key = f"{self._signal_key_prefix}{job_id}"
            self.redis.delete(key)
            logger.debug(f"Cleared cancellation signal for job {job_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to clear cancellation signal for job {job_id}: {e}")
            return False
    
    def wait_for_cancellation(self, job_id: int, check_interval: float = 1.0) -> bool:
        """
        等待取消信号（阻塞）
        
        Args:
            job_id: 作业ID
            check_interval: 检查间隔（秒）
            
        Returns:
            是否收到取消信号
        """
        while True:
            if self.is_cancelled(job_id):
                return True
            time.sleep(check_interval)
```

##### 2. 修改 JobExecutor 支持取消检查

```python
# worker/executor.py

from worker.cancellation import CancellationManager

class JobExecutor:
    """作业执行器（支持取消）"""
    
    def __init__(self, resource_manager: ResourceManager = None):
        self.settings = get_settings()
        self.resource_manager = resource_manager or ResourceManager()
        self.cancellation_manager = CancellationManager()
    
    def execute(self, job_id: int):
        """执行作业（支持取消检查）"""
        logger.info(f"🚀 Executing job {job_id}")
        
        exit_code = None
        error_occurred = False
        error_msg = None
        
        try:
            # 检查是否已被取消（执行前检查）
            if self.cancellation_manager.is_cancelled(job_id):
                raise JobCancelledError(f"Job {job_id} was cancelled before execution")
            
            # 加载作业
            job = self._load_job(job_id)
            
            # 验证状态
            if job.state != JobState.RUNNING:
                logger.error(
                    f"Job {job_id} state is {job.state.value}, expected RUNNING"
                )
                return
            
            # 分配资源
            self._mark_resources_allocated(job_id, job.allocated_cpus)
            
            # 再次检查取消（分配资源后）
            if self.cancellation_manager.is_cancelled(job_id):
                self._release_resources(job_id)
                raise JobCancelledError(f"Job {job_id} was cancelled after resource allocation")
            
            # 执行作业（支持取消检查）
            exit_code = self._run_with_cancellation(job)
            
        except JobCancelledError as e:
            logger.info(f"🛑 Job {job_id} was cancelled: {e}")
            error_occurred = True
            error_msg = str(e)
            exit_code = -15  # SIGTERM
        except Exception as e:
            logger.error(f"❌ Job {job_id} failed: {e}", exc_info=True)
            error_occurred = True
            error_msg = str(e)
        
        finally:
            # 释放资源
            self._release_resources(job_id)
            
            # 清除取消标志
            self.cancellation_manager.clear_cancellation(job_id)
            
            # 更新最终状态
            if error_occurred:
                if isinstance(error_msg, str) and "cancelled" in error_msg.lower():
                    self._mark_cancelled(job_id, error_msg)
                else:
                    self._mark_failed(job_id, error_msg)
            elif exit_code is not None:
                self._update_completion(job_id, exit_code)
            
            logger.info(f"✅ Job {job_id} finished")
    
    def _run_with_cancellation(self, job: Job) -> int:
        """运行作业脚本（支持取消检查）"""
        logger.info(f"Running job {job.id}: {job.name}")
        
        # 准备环境
        script_path = self._prepare_script(job)
        stdout_path = Path(job.work_dir) / job.stdout_path
        stderr_path = Path(job.work_dir) / job.stderr_path
        
        # 准备环境变量
        env = os.environ.copy()
        if job.environment:
            env.update(job.environment)
        
        # 执行脚本
        try:
            with open(stdout_path, "w") as stdout, open(stderr_path, "w") as stderr:
                process = subprocess.Popen(
                    ["/bin/bash", script_path],
                    stdout=stdout,
                    stderr=stderr,
                    cwd=job.work_dir,
                    env=env,
                    preexec_fn=os.setsid,
                )
                
                # 记录进程 ID
                store_pid(job.id, process.pid)
                logger.info(f"Job {job.id} started, PID: {process.pid}")
                
                # 等待完成（支持超时和取消检查）
                try:
                    timeout = job.time_limit * 60 if job.time_limit else None
                    
                    # 轮询等待，同时检查取消信号
                    start_time = time.time()
                    check_interval = 1.0  # 每秒检查一次
                    
                    while True:
                        # 检查进程是否已结束
                        exit_code = process.poll()
                        if exit_code is not None:
                            logger.info(f"Job {job.id} finished, exit code: {exit_code}")
                            return exit_code
                        
                        # 检查取消信号
                        if self.cancellation_manager.is_cancelled(job.id):
                            logger.warning(f"Job {job.id} cancellation requested, terminating...")
                            kill_process_tree(process.pid, timeout=5)
                            raise JobCancelledError(f"Job {job.id} was cancelled during execution")
                        
                        # 检查超时
                        if timeout and (time.time() - start_time) > timeout:
                            logger.warning(f"Job {job.id} timeout, terminating...")
                            kill_process_tree(process.pid, timeout=5)
                            return -1
                        
                        # 等待一段时间后再次检查
                        time.sleep(check_interval)
                        
                except subprocess.TimeoutExpired:
                    logger.warning(f"Job {job.id} timeout, terminating...")
                    kill_process_tree(process.pid, timeout=5)
                    return -1
                
        except Exception as e:
            logger.error(f"Failed to run job {job.id}: {e}")
            raise
    
    def _mark_cancelled(self, job_id: int, error_msg: str):
        """标记作业为已取消"""
        try:
            with sync_db.get_session() as session:
                if WorkerRepository.update_job_failed(
                    session, job_id, error_msg, exit_code="-1:15"
                ):
                    # 更新状态为 CANCELLED
                    job = WorkerRepository.get_job_by_id(session, job_id)
                    if job:
                        job.state = JobState.CANCELLED
                    session.commit()
        except Exception as e:
            logger.error(f"Failed to mark job {job_id} as cancelled: {e}")


class JobCancelledError(Exception):
    """作业取消异常"""
    pass
```

##### 3. 修改 API 服务支持优雅取消

```python
# api/services/job_service.py

from worker.cancellation import CancellationManager

class JobService:
    """作业操作的核心服务（支持优雅取消）"""
    
    @staticmethod
    async def cancel_job(job_id: int) -> None:
        """
        取消作业（优雅终止）
        
        流程：
        1. 设置取消标志（Redis）
        2. 等待 Worker 检测并优雅终止（可选）
        3. 如果超时，强制终止进程
        4. 更新数据库状态
        5. 释放资源
        """
        # ✅ 短事务1：查询作业
        job = await JobRepository.get_job_by_id(job_id, with_allocation=True)
        
        if job is None:
            raise JobNotFoundException(job_id)
        
        # 检查作业状态，已终止无需重复取消
        if job.state in [JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED]:
            logger.info(f"作业 {job_id} 已经处于终止状态: {job.state}")
            return
        
        # 1. 设置取消标志（通知 Worker）
        cancellation_manager = CancellationManager()
        cancellation_manager.request_cancellation(job_id)
        logger.info(f"✅ Cancellation signal sent for job {job_id}")
        
        # 2. 如果作业正在运行，等待优雅终止或强制终止
        if job.state == JobState.RUNNING:
            success = await JobService._wait_and_kill_process(job, cancellation_manager)
            if not success:
                logger.warning(f"⚠️  Failed to terminate job {job_id} process gracefully")
        
        # ✅ 短事务2：更新作业状态为已取消
        await JobRepository.update_job_state(
            job_id=job_id,
            new_state=JobState.CANCELLED,
            end_time=datetime.utcnow(),
            exit_code="-1:15",  # SIGTERM信号
        )
        
        # ✅ 短事务3：释放资源分配
        await JobRepository.release_resource_allocation(job_id)
        
        # 清除取消标志
        cancellation_manager.clear_cancellation(job_id)
        
        logger.info(f"作业 {job_id} 取消成功")
    
    @staticmethod
    async def _wait_and_kill_process(
        job: Job, 
        cancellation_manager: CancellationManager,
        graceful_timeout: int = 10,
        force_timeout: int = 5
    ) -> bool:
        """
        等待并终止进程（优雅 + 强制）
        
        Args:
            job: 作业对象
            cancellation_manager: 取消管理器
            graceful_timeout: 优雅终止超时（秒）
            force_timeout: 强制终止超时（秒）
            
        Returns:
            是否成功终止
        """
        allocation = job.resource_allocation
        
        if not allocation or not allocation.process_id:
            logger.warning(f"Job {job.id} has no process ID")
            return False
        
        pid = allocation.process_id
        
        try:
            # 检查进程是否存在
            try:
                os.kill(pid, 0)  # 信号 0 不发送信号，只检查进程是否存在
            except ProcessLookupError:
                logger.info(f"Job {job.id} process {pid} already terminated")
                return True
            
            # 等待优雅终止（Worker 检测到取消信号后会终止进程）
            logger.info(f"Waiting for graceful termination of job {job.id} (PID: {pid})...")
            
            start_time = time.time()
            check_interval = 0.5
            
            while (time.time() - start_time) < graceful_timeout:
                # 检查进程是否已结束
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    logger.info(f"✅ Job {job.id} process {pid} terminated gracefully")
                    return True
                
                # 检查取消标志是否已清除（Worker 可能已经处理）
                if not cancellation_manager.is_cancelled(job.id):
                    # 取消标志已清除，可能 Worker 已经处理完成
                    # 再次检查进程
                    try:
                        os.kill(pid, 0)
                        # 进程还在，继续等待
                    except ProcessLookupError:
                        logger.info(f"✅ Job {job.id} process {pid} terminated gracefully")
                        return True
                
                await asyncio.sleep(check_interval)
            
            # 优雅终止超时，强制终止
            logger.warning(
                f"Job {job.id} process {pid} did not terminate gracefully within "
                f"{graceful_timeout}s, forcing termination..."
            )
            
            # 使用 kill_process_tree 强制终止
            from worker.process_utils import kill_process_tree
            kill_process_tree(pid, timeout=force_timeout)
            
            # 验证进程是否已终止
            try:
                os.kill(pid, 0)
                logger.error(f"❌ Job {job.id} process {pid} still exists after force kill")
                return False
            except ProcessLookupError:
                logger.info(f"✅ Job {job.id} process {pid} terminated forcefully")
                return True
                
        except Exception as e:
            logger.error(f"Failed to terminate job {job.id} process {pid}: {e}")
            return False
```

---

### 方案 2: 数据库标志机制（备选）

如果不想依赖 Redis，可以使用数据库标志：

```python
# 在 Job 模型中添加字段
class Job(SQLModel, table=True):
    cancellation_requested: bool = Field(default=False, description="是否请求取消")
    cancellation_time: Optional[datetime] = Field(default=None, description="取消请求时间")

# Worker 定期查询数据库检查取消标志
def _check_cancellation(self, job_id: int) -> bool:
    with sync_db.get_session() as session:
        job = WorkerRepository.get_job_by_id(session, job_id)
        return job.cancellation_requested if job else False
```

**缺点**：
- 需要频繁查询数据库
- 性能不如 Redis
- 增加数据库负载

---

## 🔧 改进进程终止工具

### 增强 kill_process_tree

```python
# worker/process_utils.py

def kill_process_tree(pid: int, timeout: int = 5, signal_first: int = signal.SIGTERM) -> bool:
    """
    终止进程树（增强版）
    
    Args:
        pid: 进程 ID
        timeout: 超时时间（秒）
        signal_first: 首先发送的信号（默认 SIGTERM）
        
    Returns:
        是否成功终止
    """
    try:
        # 1. 检查进程是否存在
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            logger.debug(f"Process {pid} does not exist")
            return True
        
        # 2. 获取进程组 ID
        try:
            pgid = os.getpgid(pid)
        except ProcessLookupError:
            logger.warning(f"Process {pid} does not exist (race condition)")
            return True
        
        # 3. 发送第一个信号（通常是 SIGTERM）
        try:
            os.killpg(pgid, signal_first)
            logger.info(f"Sent {signal_first} to process group {pgid} (PID: {pid})")
        except ProcessLookupError:
            logger.warning(f"Process group {pgid} does not exist")
            return True
        
        # 4. 等待进程结束
        start_time = time.time()
        check_interval = 0.1
        
        while (time.time() - start_time) < timeout:
            try:
                os.kill(pid, 0)  # 检查进程是否存在
                time.sleep(check_interval)
            except ProcessLookupError:
                logger.info(f"✅ Process {pid} terminated gracefully")
                return True
        
        # 5. 超时，发送 SIGKILL
        logger.warning(f"Process {pid} did not terminate within {timeout}s, sending SIGKILL")
        try:
            os.killpg(pgid, signal.SIGKILL)
            
            # 再次等待
            time.sleep(0.5)
            
            # 验证进程是否已终止
            try:
                os.kill(pid, 0)
                logger.error(f"❌ Process {pid} still exists after SIGKILL")
                return False
            except ProcessLookupError:
                logger.info(f"✅ Process {pid} terminated forcefully")
                return True
                
        except ProcessLookupError:
            # 进程在发送 SIGKILL 前已结束
            logger.info(f"Process {pid} terminated before SIGKILL")
            return True
        
    except PermissionError:
        logger.error(f"Permission denied when killing process {pid}")
        return False
    except Exception as e:
        logger.error(f"Failed to kill process {pid}: {e}")
        return False
```

---

## 📊 方案对比

| 特性 | Redis 信号机制 | 数据库标志机制 |
|------|---------------|---------------|
| **性能** | ⭐⭐⭐⭐⭐ 高 | ⭐⭐⭐ 中 |
| **实时性** | ⭐⭐⭐⭐⭐ 高 | ⭐⭐⭐ 中 |
| **复杂度** | ⭐⭐⭐ 中 | ⭐⭐⭐⭐ 低 |
| **依赖** | Redis | 数据库 |
| **推荐度** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |

---

## 🚀 实施步骤

### 阶段 1: 基础实现（1-2 天）
1. 创建 `CancellationManager` 类
2. 修改 `JobExecutor` 支持取消检查
3. 修改 `JobService.cancel_job()` 使用新机制

### 阶段 2: 测试验证（1-2 天）
1. 单元测试
2. 集成测试
3. 压力测试

### 阶段 3: 优化和文档（1 天）
1. 性能优化
2. 错误处理完善
3. 文档更新

---

## ⚠️ 注意事项

### 1. 信号检查频率
- 不要过于频繁（影响性能）
- 建议：1-2 秒检查一次

### 2. 超时设置
- 优雅终止超时：10-30 秒
- 强制终止超时：5 秒

### 3. 进程状态检查
- 始终检查进程是否存在
- 处理竞态条件（进程在检查时结束）

### 4. 资源清理
- 确保资源在取消时正确释放
- 清除取消标志

### 5. 错误处理
- 处理进程不存在的情况
- 处理权限不足的情况
- 处理进程已结束的情况

---

## 🎯 总结

**推荐方案**：Redis 信号机制 + 优雅终止

**优势**：
- ✅ 跨进程通信
- ✅ 实时响应
- ✅ 优雅终止
- ✅ 强制终止兜底
- ✅ 资源正确释放

**实施难度**：中（2-3 天）

**风险**：低（向后兼容，可逐步启用）

通过这个方案，可以实现：
1. **优雅取消**：Worker 检测到取消信号后优雅终止
2. **强制终止**：如果优雅终止失败，强制 kill
3. **资源清理**：确保资源正确释放
4. **状态同步**：数据库状态与实际进程状态一致

